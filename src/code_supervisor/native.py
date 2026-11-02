"""C++ 官方文档、真实构建、静态分析、覆盖率和运行时验证。"""

import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .checks import finding
from .tasks import CheckError, run, save, selected_files, snapshot, tool


def doxygen(root, files, options, output):
    """使用官方 Doxygen 处理声明与文档，收集警告及生成的 XML。"""
    names = selected_files(root, files, options, "cpp")

    def quote(p):
        """为 Doxygen 配置路径添加引号。"""
        return '"' + str(p).replace("\\", "/").replace('"', '\\"') + '"'

    config = output / "Doxyfile"
    warnings = output / "doxygen-warnings.log"
    config.write_text(
        "\n".join(
            [
                "PROJECT_NAME = Supervisor",
                "OUTPUT_DIRECTORY = " + quote(output / "doxygen"),
                "INPUT = " + " ".join(quote(root / n) for n in names),
                "INPUT_ENCODING = UTF-8",
                "RECURSIVE = NO",
                "QUIET = YES",
                "GENERATE_HTML = YES",
                "GENERATE_LATEX = NO",
                "GENERATE_XML = YES",
                "EXTRACT_ALL = NO",
                "EXTRACT_PRIVATE = YES",
                "EXTRACT_STATIC = YES",
                "WARNINGS = YES",
                "WARN_IF_UNDOCUMENTED = YES",
                "WARN_IF_DOC_ERROR = YES",
                "WARN_NO_PARAMDOC = YES",
                "WARN_LOGFILE = " + quote(warnings),
                "ENABLE_PREPROCESSING = YES",
                "MACRO_EXPANSION = NO",
                "HAVE_DOT = NO",
            ]
        )
        + "\n"
    )
    log, _ = run(
        [options.get("executable") or tool("doxygen"), str(config)],
        root,
        output,
        "doxygen",
        options.get("timeout", 120),
    )
    index = output / "doxygen/xml/index.xml"
    if not index.exists():
        raise CheckError(f"Doxygen 未生成 XML，查看 {log}")
    tree = ET.parse(index)
    if not tree.findall(".//compound"):
        raise CheckError("Doxygen 没有识别文档对象")
    issues = []
    for line in warnings.read_text().splitlines():
        match = re.match(r"(.+?):(\d+):\s*(?:warning|error):\s*(.*)", line)
        if match:
            issues.append(finding(match[1], int(match[2]), "DOXYGEN", match[3]))
        elif line.strip():
            issues.append(finding("", 1, "DOXYGEN", line))
    return dict(
        status="fail" if issues else "pass",
        findings=issues,
        evidence=str(index),
        scope="官方 Doxygen 文档警告；不能证明中文说明与实现一致",
    )


def prepare(root, options, output, flags=""):
    """在隔离副本中配置并构建 CMake 工程，不使用旧二进制。"""
    work = snapshot(root, output, options)
    source = work / options.get("cmake_source", ".")
    if not source.resolve().is_relative_to(work):
        raise CheckError("cmake_source 越界")
    build = work / ".build"
    command = [
        tool("cmake"),
        "-S",
        str(source),
        "-B",
        str(build),
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        "-DCMAKE_BUILD_TYPE=Debug",
    ]
    if flags:
        command += [
            "-DCMAKE_C_FLAGS=" + flags,
            "-DCMAKE_CXX_FLAGS=" + flags,
            "-DCMAKE_EXE_LINKER_FLAGS=" + flags,
            "-DCMAKE_SHARED_LINKER_FLAGS=" + flags,
        ]
    command += options.get("configure_args", [])
    run(command, work, output, "configure", options.get("timeout", 180))
    build_project(work, build, options, output, "build")
    if flags:
        entries = json.loads((build / "compile_commands.json").read_text())
        own = [
            entry
            for entry in entries
            if Path(entry["file"]).resolve().is_relative_to(work)
        ]
        marker = flags.split()[0]
        if not own or any(
            marker not in entry.get("command", " ".join(entry.get("arguments", [])))
            for entry in own
        ):
            raise CheckError("构建覆盖了所需插桩参数，不能证明运行了检测版本")
    return work, build


def build_project(work, build, options, output, label):
    """执行真实增量构建；变异测试另行强制清理，避免旧产物冒充结果。"""
    return run(
        [
            tool("cmake"),
            "--build",
            str(build),
            "--parallel",
            str(options.get("jobs", 2)),
        ],
        work,
        output,
        label,
        options.get("timeout", 180),
    )


def test_project(work, build, options, output, label, accept_failure=False):
    """运行 CTest 并验证非空 JUnit，返回通过或发现失败。

    无测试、测试未执行、进程异常、Sanitizer运行库失败都不算成功证据。
    """
    junit = output / (label + ".xml")
    log, code = run(
        [
            tool("ctest"),
            "--test-dir",
            str(build),
            "--output-on-failure",
            "--no-tests=error",
            "--output-junit",
            str(junit),
        ],
        work,
        output,
        label,
        options.get("timeout", 180),
        accepted=(0, 8) if accept_failure else (0,),
    )
    tree = ET.parse(junit)
    cases = tree.findall(".//testcase")
    if not cases or any(c.find("skipped") is not None for c in cases):
        raise CheckError("CTest 没有执行测试或存在跳过项")
    text = log.read_text(errors="replace")
    if (
        "unexpected memory mapping" in text
        or "ASan runtime does not come first" in text
        or "LeakSanitizer has encountered a fatal error" in text
    ):
        raise CheckError("Sanitizer 运行环境不兼容，不能判断业务代码")
    return code, log, len(cases)


def cpp_build(root, files, options, output):
    """在新副本构建并运行非空 C++ 测试套件。"""
    work, build = prepare(root, options, output)
    code, log, count = test_project(work, build, options, output, "ctest", True)
    return dict(
        status="pass" if code == 0 else "fail",
        findings=[],
        tests=count,
        evidence=str(log),
        scope="隔离 CMake 构建＋CTest；范围由 inputs/cmake_source 配置决定",
    )


def clang_tidy(root, files, options, output):
    """使用本次真实构建的编译数据库逐个分析自有翻译单元。"""
    work, build = prepare(root, options, output)
    database = build / "compile_commands.json"
    entries = json.loads(database.read_text())
    units = sorted(
        {
            str(Path(e["file"]).resolve())
            for e in entries
            if Path(e["file"]).resolve().is_relative_to(work)
        }
    )
    if not units:
        raise CheckError("编译数据库不含自有翻译单元")
    issues = []
    for index, name in enumerate(units):
        log, code = run(
            [
                tool("clang-tidy"),
                name,
                "-p",
                str(build),
                "--checks=-*,clang-analyzer-*,bugprone-*,performance-*",
                "--warnings-as-errors=*",
            ],
            work,
            output,
            f"tidy-{index}",
            options.get("timeout", 180),
            accepted=(0, 1),
        )
        text = log.read_text(errors="replace")
        if "clang-diagnostic-error" in text:
            raise CheckError(f"Clang 无法解析真实构建配置：{log}")
        for match in re.finditer(
            r"^(.+?):(\d+):\d+: (?:warning|error): (.+)$", text, re.M
        ):
            issues.append(finding(match[1], int(match[2]), "CLANG-TIDY", match[3]))
        if code and not issues:
            raise CheckError(f"clang-tidy失败且无可解析诊断：{log}")
    return dict(
        status="fail" if issues else "pass",
        findings=issues,
        translation_units=units,
        scope="本轮编译数据库中的自有翻译单元；头文件按包含关系分析",
    )


def cpp_coverage(root, files, options, output):
    """重新插桩构建和测试，以 gcovr 采集本轮 C++ 行覆盖率。"""
    work, build = prepare(root, options, output, "--coverage -O0 -g")
    test_project(work, build, options, output, "coverage-tests")
    path = output / "gcovr.json"
    run(
        [tool("gcovr"), "--root", str(work), "--json", str(path), str(build)],
        work,
        output,
        "gcovr",
        options.get("timeout", 180),
    )
    data = json.loads(path.read_text())
    names = selected_files(root, files, options, "cpp")
    rows = [row for row in data.get("files", []) if row["file"] in names]
    if set(names) - {row["file"] for row in rows}:
        raise CheckError("选定 C++ 文件缺少覆盖数据，请核对构建和 files 范围")
    total = sum(
        len([line for line in f["lines"] if not line.get("gcovr/noncode", False)])
        for f in rows
    )
    covered = sum(
        sum(
            line.get("count", 0) > 0
            for line in f["lines"]
            if not line.get("gcovr/noncode", False)
        )
        for f in rows
    )
    if not total:
        raise CheckError("覆盖率可执行行数为0")
    rate = 100 * covered / total
    threshold = options.get("minimum", 80)
    issues = (
        []
        if rate >= threshold
        else [finding("", 1, "CPP-COVERAGE", f"行覆盖率 {rate:.2f}% < {threshold}%")]
    )
    return dict(
        status="fail" if issues else "pass",
        findings=issues,
        coverage=rate,
        evidence=str(path),
        scope="GCC/gcovr 本次插桩运行，覆盖率不是正确率",
    )


def sanitizers(root, files, options, output):
    """分别构建地址/未定义行为或线程检查版本，并运行实际测试。"""
    kind = options.get("kind", "address,undefined")
    if kind not in {"address,undefined", "thread"}:
        raise CheckError(
            "kind 只允许 address,undefined 或 thread，不能合并 ASan 和 TSan"
        )
    work, build = prepare(
        root,
        options,
        output,
        f"-fsanitize={kind} -fno-sanitize-recover=all -fno-omit-frame-pointer -g",
    )
    code, log, count = test_project(
        work, build, options, output, "sanitizer-tests", True
    )
    issues = (
        []
        if code == 0
        else [finding("", 1, "SANITIZER", "运行时检查或测试失败，请查看日志")]
    )
    return dict(
        status="pass" if code == 0 else "fail",
        findings=issues,
        tests=count,
        evidence=str(log),
        scope=f"实际执行的 {kind} 测试路径；未执行时序不作保证",
    )


def cpp_complexity(root, files, options, output):
    """使用 Lizard 计算 C++ 函数复杂度，不伪造缺少覆盖率的 CRAP。"""
    import lizard

    rows = []
    for name in selected_files(root, files, options, "cpp"):
        info = lizard.analyze_file(str(root / name))
        for function in info.function_list:
            rows.append(
                dict(
                    file=name,
                    line=function.start_line,
                    name=function.long_name,
                    complexity=function.cyclomatic_complexity,
                )
            )
    if not rows:
        raise CheckError("Lizard 未识别 C++ 函数")
    issues = [
        finding(
            r["file"], r["line"], "CPP-COMPLEXITY", f'{r["name"]}: CC={r["complexity"]}'
        )
        for r in rows
        if r["complexity"] >= options.get("threshold", 10)
    ]
    return dict(
        status="fail" if issues else "pass",
        findings=issues,
        evidence=save(output, "complexity", rows),
        scope="独立复杂度指标；未与覆盖率可靠匹配时不计算 CRAP",
    )


def cpp_duplicates(root, files, options, output):
    """使用固定 jscpd 的 JSON 克隆记录判定 C++ 重复候选。"""
    names = selected_files(root, files, options, "cpp")
    command = [
        tool("jscpd"),
        "--format",
        "cpp",
        "--reporters",
        "json",
        "--output",
        str(output),
        "--min-lines",
        str(options.get("min_lines", 5)),
        "--min-tokens",
        str(options.get("min_tokens", 50)),
        *[str(root / n) for n in names],
    ]
    run(command, root, output, "jscpd", options.get("timeout", 120))
    path = output / "jscpd-report.json"
    data = json.loads(path.read_text())
    total = data["statistics"]["total"]
    if total.get("sources", 0) == 0:
        raise CheckError("jscpd 没有扫描任何文件")
    issues = [
        finding(
            d["firstFile"]["name"],
            d["firstFile"]["start"],
            "CPP-DUPLICATE",
            f'与 {d["secondFile"]["name"]}:{d["secondFile"]["start"]} 存在克隆候选',
        )
        for d in data["duplicates"]
    ]
    return dict(
        status="fail" if issues else "pass",
        findings=issues,
        evidence=str(path),
        scope="jscpd token 克隆检测，非 dryer 相似度；阈值以下重复可能被省略",
    )


def mutation_sites(source):
    """仅提取函数体中的 C++ 二元运算符，忽略注释、字符串和声明。"""
    from tree_sitter import Language, Parser
    import tree_sitter_cpp
    from .cpp import nodes

    tree = Parser(Language(tree_sitter_cpp.language())).parse(source)
    if tree.root_node.has_error:
        raise CheckError("C++ 变异输入无法完整解析；不猜测宏展开结构")
    replacements = {
        "+": "-",
        "-": "+",
        "*": "/",
        "/": "*",
        "<": "<=",
        ">": ">=",
        "==": "!=",
        "!=": "==",
        "&&": "||",
        "||": "&&",
    }
    found = []
    for node in nodes(tree.root_node):
        if node.type != "binary_expression":
            continue
        parent = node.parent
        while parent and parent.type != "function_definition":
            parent = parent.parent
        if parent is None:
            continue
        for child in node.children:
            text = child.text.decode()
            if not child.is_named and text in replacements:
                found.append(
                    dict(
                        start=child.start_byte,
                        end=child.end_byte,
                        line=child.start_point.row + 1,
                        original=text,
                        replacement=replacements[text],
                    )
                )
    return found


def cpp_mutation(root, files, options, output):
    """逐个修改隔离 C++ 源码、强制重新构建并执行测试。

    这是有限二元算子变异后端，不冒充 Mull。编译无效、执行错误和预算未完成单列。
    仅测试失败算杀死；无已执行有效变异不能通过。
    """
    names = selected_files(root, files, options, "cpp")
    work, build = prepare(root, options, output)
    test_project(work, build, options, output, "baseline")
    records = []
    executed = 0
    for name in names:
        path = work / name
        if not path.is_file():
            raise CheckError(f"inputs 没有包含 {name}")
        original = path.read_bytes()
        for site in mutation_sites(original):
            record = dict(site, file=name)
            if executed >= options.get("max_mutants", 30):
                record["outcome"] = "budget-exhausted"
            else:
                path.write_bytes(
                    original[: site["start"]]
                    + site["replacement"].encode()
                    + original[site["end"] :]
                )
                try:
                    log, code = run(
                        [
                            tool("cmake"),
                            "--build",
                            str(build),
                            "--clean-first",
                            "--parallel",
                            "2",
                        ],
                        work,
                        output,
                        f"mutant-build-{len(records)}",
                        options.get("timeout", 180),
                        accepted=(0, 1, 2),
                    )
                    if code:
                        record["outcome"] = "invalid"
                    else:
                        code, log, _ = test_project(
                            work,
                            build,
                            options,
                            output,
                            f"mutant-test-{len(records)}",
                            True,
                        )
                        record["outcome"] = "survived" if code == 0 else "killed"
                        executed += 1
                except CheckError as exc:
                    record.update(outcome="error", reason=str(exc))
                finally:
                    path.write_bytes(original)
            records.append(record)
    issues = [
        finding(
            r["file"],
            r["line"],
            "CPP-MUTATION",
            "变异存活：" + r["original"] + " → " + r["replacement"],
        )
        for r in records
        if r["outcome"] == "survived"
    ]
    incomplete = not executed or any(
        r["outcome"] in {"error", "budget-exhausted"} for r in records
    )
    return dict(
        status="error" if incomplete else "fail" if issues else "pass",
        findings=issues,
        executed=executed,
        evidence=save(output, "cpp-mutation", records),
        scope="有限二元算子变异；每项重新构建，不能替代所有 C++ 故障类型或 Mull 全部算子",
    )
