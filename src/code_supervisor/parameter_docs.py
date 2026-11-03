"""逐参数核对中文说明，保留配置范围与解析失败证据。"""

import ast
import hashlib
import re

from .checks import CHINESE, finding
from .config import inside, walk
from .cpp import nodes, preceding, targets
from .tasks import CheckError, save


def google_arguments(doc):
    """解析Google参数分区，返回参数到含续行说明的映射。

    Args:
        doc: 已去除公共缩进的文档字符串。

    Returns:
        去除星号后的参数名称及对应说明。
    """
    entries = {}
    active = False
    current = None
    indent = 0
    for line in doc.splitlines():
        if re.fullmatch(r"(Args|Arguments|Keyword Args):", line):
            active, current = True, None
            continue
        if line and not line[0].isspace():
            active, current = False, None
        if not active:
            continue
        match = re.match(r"^(\s+)(\*{0,2}\w+)(?:\s*\([^)]*\))?:\s*(.*)$", line)
        if match and (current is None or len(match[1]) <= indent):
            indent = len(match[1])
            current = match[2].lstrip("*")
            entries[current] = match[3]
        elif current and len(line) - len(line.lstrip()) > indent:
            entries[current] += "\n" + line.strip()
    return entries


def python_parameters(source):
    """解析Python显式参数，方法接收者除外；匿名函数参数保留为待补说明。

    Args:
        source: Python源码文本，支持无后缀入口。

    Returns:
        参数位置、名称、对应说明与例外列表。
    """
    tree = ast.parse(source)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    records, exceptions = [], []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        args += [a for a in (node.args.vararg, node.args.kwarg) if a]
        owner = parents.get(node)
        method = isinstance(owner, ast.ClassDef)
        doc = "" if isinstance(node, ast.Lambda) else ast.get_docstring(node) or ""
        if method and node.name == "__init__" and not doc:
            doc = ast.get_docstring(owner) or ""
        entries = google_arguments(doc)
        for index, arg in enumerate(args):
            decorators = [
                getattr(d, "id", "") for d in getattr(node, "decorator_list", [])
            ]
            if (
                method
                and index == 0
                and arg.arg in {"self", "cls"}
                and "staticmethod" not in decorators
            ):
                exceptions.append(
                    dict(line=arg.lineno, parameter=arg.arg, reason="实例/类方法接收者")
                )
                continue
            records.append(
                dict(
                    line=arg.lineno,
                    parameter=arg.arg,
                    description=entries.get(arg.arg, ""),
                    owner=getattr(node, "name", "<lambda>"),
                )
            )
    return records, exceptions


def doxygen_arguments(doc):
    """读取Doxygen参数标签及其续行，支持方向标记和同标签多个参数。

    Args:
        doc: 紧邻函数的Doxygen文档块。

    Returns:
        参数名称到说明的映射。
    """
    cleaned = re.sub(r"^\s*(?:/\*\*|///|\*)\s?", "", doc, flags=re.M).replace("*/", "")
    pattern = r"[@\\]param\s*(?:\[[^\]]+\]\s*)?([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s+(.*?)(?=[@\\]\w+|$)"
    result = {}
    for match in re.finditer(pattern, cleaned, re.S):
        for name in match[1].split(","):
            result[name.strip()] = match[2].strip()
    return result


def cpp_parameters(source):
    """读取可解析C++声明/定义的具名形参，解析错误不会当作全部通过。

    Args:
        source: UTF-8源码字节。

    Returns:
        参数记录、未命名形参例外、语法树是否完整。
    """
    from tree_sitter import Language, Parser
    import tree_sitter_cpp

    tree = Parser(Language(tree_sitter_cpp.language())).parse(source)
    records, exceptions = [], []
    for node in targets(tree):
        if node.type in {"class_specifier", "struct_specifier", "enum_specifier"}:
            continue
        declarator = node.child_by_field_name("declarator")
        if declarator is None:
            continue
        function = next(
            (n for n in nodes(declarator) if n.type == "function_declarator"), None
        )
        if function is None:
            continue
        params = function.child_by_field_name("parameters")
        if params is None:
            continue
        entries = doxygen_arguments(preceding(node, source))
        for param in params.named_children:
            if param.type not in {
                "parameter_declaration",
                "optional_parameter_declaration",
                "variadic_parameter_declaration",
            }:
                continue
            declaration = param.child_by_field_name("declarator")
            identifier = (
                next((n for n in nodes(declaration) if n.type == "identifier"), None)
                if declaration
                else None
            )
            if identifier is None:
                if param.text.strip() != b"void":
                    exceptions.append(
                        dict(
                            line=param.start_point.row + 1,
                            parameter=param.text.decode(),
                            reason="未命名形参；需人工核对接口说明",
                        )
                    )
                continue
            name = identifier.text.decode()
            records.append(
                dict(
                    line=param.start_point.row + 1,
                    parameter=name,
                    description=entries.get(name, ""),
                    owner="C++函数",
                )
            )
    return records, exceptions, not tree.root_node.has_error


def preceding_yaml_comment(lines, row, column):
    """仅接受紧邻且同层级的中文注释，不将文件头自动分配给所有键。

    Args:
        lines: YAML原始文本行。
        row: 键的零基行号。
        column: 键的零基列号。

    Returns:
        紧邻注释文本。
    """
    comments = []
    indent = len(lines[row]) - len(lines[row].lstrip())
    for index in range(row - 1, -1, -1):
        line = lines[index]
        if not line.lstrip().startswith("#") or len(line) - len(line.lstrip()) not in {
            indent,
            column,
        }:
            break
        comments.insert(0, line.lstrip()[1:].strip())
    return "\n".join(comments)


def yaml_parameters(source):
    """检查YAML各映射键的同层注释，标量数组由所属键说明。

    Args:
        source: YAML文本；标量内部的井号不当作注释。

    Returns:
        参数路径与说明列表，包含容器键和序列中的映射键。

    Raises:
        ValueError: 出现复杂键、重复键或循环别名。
    """
    import yaml

    lines = source.splitlines()
    tokens = list(yaml.scan(source))
    records = []

    def visit(node, path, ancestors):
        """遍历映射和序列，检查别名循环。

        Args:
            node: YAML语法节点。
            path: 当前参数的完整路径。
            ancestors: 当前递归路径上的节点标识。
        """
        if id(node) in ancestors:
            raise ValueError("配置存在循环别名")
        ancestors = ancestors | {id(node)}
        if isinstance(node, yaml.MappingNode):
            seen = set()
            for key, value in node.value:
                if not isinstance(key, yaml.ScalarNode) or key.value in seen:
                    raise ValueError("复杂键或重复键不能可靠关联注释")
                seen.add(key.value)
                row, column = key.start_mark.line, key.start_mark.column
                name = path + "." + key.value if path else key.value
                doc = (
                    ""
                    if node.flow_style
                    else preceding_yaml_comment(lines, row, column)
                )
                # 只在本行最后一个语法token后读取注释，避免字符串中的#冒充说明。
                if not node.flow_style:
                    line_tokens = [
                        t
                        for t in tokens
                        if t.start_mark.line == row and t.end_mark.line == row
                    ]
                    end = max(
                        (t.end_mark.column for t in line_tokens),
                        default=len(lines[row]),
                    )
                    tail = lines[row][end:].strip()
                    if tail.startswith("#"):
                        doc += "\n" + tail[1:].strip()
                records.append(
                    dict(
                        line=row + 1, parameter=name, description=doc, owner="YAML配置"
                    )
                )
                visit(value, name, ancestors)
        elif isinstance(node, yaml.SequenceNode):
            for index, value in enumerate(node.value):
                visit(value, f"{path}[{index}]", ancestors)

    for tree in yaml.compose_all(source):
        if tree is not None:
            visit(tree, "", set())
    return records


def config_files(root, paths):
    """发现显式配置范围中的文件，拒绝缺失路径和符号链接。

    Args:
        root: 工程根目录。
        paths: 文件或目录的相对路径列表。

    Returns:
        去重排序后的配置路径；目录扫描识别YAML/JSON/TOML/INI/XML/SDF。
    """
    found = set()
    for name in paths:
        path = inside(root, name)
        if not path.exists() or (root / name).is_symlink():
            raise CheckError(f"配置参数路径不存在或为链接：{name}")
        for item in [path] if path.is_file() else walk(path):
            if item.suffix.lower() in {
                ".yaml",
                ".yml",
                ".toml",
                ".json",
                ".ini",
                ".xml",
                ".sdf",
            }:
                found.add(item.relative_to(root).as_posix())
    return sorted(found)


def parameter_docs(root, files, options, output):
    """检查所有选定源码的函数参数及显式配置范围的参数注释。

    Args:
        root: 项目根目录。
        files: Supervisor扫描得到的源码与语言映射。
        options: paths明确列出配置文件或目录，空列表表示显式只查函数。
        output: 本次独立证据目录。

    Returns:
        参数级诊断、例外、配置哈希和未解析范围；不自动判断说明真实性。
    """
    if "paths" not in options:
        raise CheckError("parameter-docs必须显式配置paths；仅查函数时填写空列表")
    configs = config_files(root, options["paths"])
    all_files = {**files, **{name: "config" for name in configs}}
    issues, exceptions, errors, counts, hashes = [], [], [], {}, {}
    for name, language in all_files.items():
        data = (root / name).read_bytes()
        hashes[name] = hashlib.sha256(data).hexdigest()
        try:
            if language == "python":
                rows, skipped = python_parameters(data.decode("utf-8-sig"))
            elif language == "cpp":
                rows, skipped, complete = cpp_parameters(data)
                if not complete:
                    errors.append(
                        dict(
                            file=name, reason="C++语法未完整解析，宏展开接口需人工核对"
                        )
                    )
            elif (root / name).suffix.lower() in {".yaml", ".yml"}:
                rows, skipped = yaml_parameters(data.decode("utf-8-sig")), []
            else:
                errors.append(
                    dict(file=name, reason="当前参数注释适配器未实现此配置格式")
                )
                continue
            counts[name] = len(rows)
            exceptions += [dict(item, file=name) for item in skipped]
            for item in rows:
                if not CHINESE.search(item["description"]):
                    rule = {
                        "python": "PY-PARAM-DOC",
                        "cpp": "CPP-PARAM-DOC",
                        "config": "CONFIG-PARAM-DOC",
                    }[language]
                    issues.append(
                        finding(
                            name,
                            item["line"],
                            rule,
                            f'{item["owner"]}参数 {item["parameter"]} 缺少对应中文说明',
                        )
                    )
        except Exception as exc:
            errors.append(dict(file=name, reason=f"{type(exc).__name__}: {exc}"))
    if config_files(root, options["paths"]) != configs:
        errors.append(dict(file="", reason="检查期间配置文件清单变化"))
    for name, digest in hashes.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            errors.append(dict(file=name, reason="检查期间内容变化"))
    evidence = save(
        output,
        "parameter-docs",
        dict(counts=counts, exceptions=exceptions, errors=errors, hashes=hashes),
    )
    return dict(
        status="error" if errors else "fail" if issues else "pass",
        findings=issues,
        parameter_count=sum(counts.values()),
        configuration_files=configs,
        exceptions=exceptions,
        unparsed=errors,
        evidence=evidence,
        scope="显式Python/C++函数形参与YAML映射键；self/cls接收者、C++未命名形参单列；其他配置格式未实现时报告错误。注释单位、范围与真实性仍须语义审查。",
    )
