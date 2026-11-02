"""Python 文档与排版检查，以及固定规则集的 Ruff 适配。"""

import ast
import importlib.metadata
import re
import sys
import tomllib

from .process import execute

CHINESE = re.compile(r"[\u4e00-\u9fff]")


def finding(file, line, rule, message):
    """构造包含定位信息的统一诊断记录。"""
    return dict(file=file, line=line, rule=rule, message=message)


def python_docs(root, files):
    """检查全部语法定义的中文说明与三双引号，不推断契约是否真实。"""
    issues = []
    for file in files:
        source = (root / file).read_text(encoding="utf-8-sig")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            issues.append(finding(file, exc.lineno, "PY-SYNTAX", str(exc)))
            continue
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            if isinstance(node, ast.Module) and not node.body:
                continue
            doc = ast.get_docstring(node)
            line = getattr(node, "lineno", 1)
            if not doc:
                issues.append(finding(file, line, "PY-DOC", "缺少文档字符串"))
            elif not CHINESE.search(doc):
                issues.append(finding(file, line, "PY-CN", "文档缺少中文说明"))
            else:
                literal = ast.get_source_segment(source, node.body[0].value)
                if not re.match(r'(?i)^[ru]*"""', literal):
                    issues.append(finding(file, line, "PY-QUOTE", "文档须使用三双引号"))
                if re.search(r"@(param|return)\b", doc):
                    issues.append(
                        finding(
                            file,
                            line,
                            "PY-GOOGLE",
                            "请用 Google 分区，不使用 Doxygen 标签",
                        )
                    )
    return {
        "status": "fail" if issues else "pass",
        "findings": issues,
        "scope": "中文文档存在性、引号、标签及 Python 语法；不代表完整 Google 指南认证",
    }


def black_check(root, files):
    """在内存比较 Black 格式，读取工程 pyproject.toml，不写回源码。"""
    import black

    options = {}
    config = root / "pyproject.toml"
    if config.exists():
        options = tomllib.loads(config.read_text()).get("tool", {}).get("black", {})
    supported = {
        "line-length",
        "target-version",
        "skip-string-normalization",
        "skip-magic-trailing-comma",
        "extend-exclude",
        "exclude",
        "include",
        "force-exclude",
    }
    if set(options) - supported:
        return {
            "status": "error",
            "reason": f"第一版尚不支持这些 Black 配置：{sorted(set(options) - supported)}",
        }
    mode = black.Mode(
        line_length=options.get("line-length", 88),
        target_versions={
            black.TargetVersion[v.upper()] for v in options.get("target-version", [])
        },
        string_normalization=not options.get("skip-string-normalization", False),
        magic_trailing_comma=not options.get("skip-magic-trailing-comma", False),
    )
    issues = []
    for file in files:
        try:
            black.format_file_contents(
                (root / file).read_text(encoding="utf-8-sig"), fast=False, mode=mode
            )
        except black.NothingChanged:
            continue
        except black.InvalidInput as exc:
            issues.append(finding(file, 1, "BLACK-PARSE", str(exc)))
        else:
            issues.append(
                finding(file, 1, "BLACK-FORMAT", "排版与项目 Black 配置不一致")
            )
    return {
        "status": "fail" if issues else "pass",
        "findings": issues,
        "version": black.__version__,
        "scope": "检查督导配置选中的全部 Python 文件；排除范围以 supervisor 配置为准",
    }


def ruff_check(root, files, output):
    """逐文件检查选定静态规则和 Google 文档分区，包含无后缀入口。"""
    import json

    version = importlib.metadata.version("ruff")
    issues = []
    logs = []
    for index, file in enumerate(files):
        # 强制显式固定规则，不继承外部 fix 或 preview 配置。
        argv = [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--isolated",
            "--no-cache",
            "--no-fix",
            "--output-format",
            "json",
            "--select",
            "F,E4,E7,E9,D200,D205,D209,D300,D405,D410,D411,D416",
            "--",
            str(root / file),
        ]
        log = output / f"ruff-{index}.json"
        result = execute(argv, root, log)
        logs.append(str(log))
        if result["status"] == "error":
            return dict(result, logs=logs, version=version)
        try:
            records = json.loads(log.read_text())
        except (ValueError, OSError) as exc:
            return {"status": "error", "reason": str(exc), "logs": logs}
        for item in records:
            issues.append(
                finding(file, item["location"]["row"], item["code"], item["message"])
            )
    return {
        "status": "fail" if issues else "pass",
        "findings": issues,
        "version": version,
        "logs": logs,
        "scope": "固定静态规则及文档分区子集；不检查完整 Google 导入、类型、契约规则",
    }
