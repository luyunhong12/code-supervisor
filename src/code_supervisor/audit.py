"""类型、依赖边界、源码安全、凭据与依赖漏洞的独立检查。"""

import ast
import importlib.util
import json
import re

from .checks import finding
from .config import inside, walk
from .tasks import CheckError, run, save, selected_files, tool


def pyright(root, files, options, output):
    """运行 Pyright JSON 诊断，拒绝零文件分析或损坏结果。"""
    names = selected_files(root, files, options, "python")
    command = [tool("pyright"), "--outputjson"]
    if options.get("config"):
        command += ["--project", str(inside(root, options["config"]))]
    command += [str(root / name) for name in names]
    log, _ = run(
        command, root, output, "pyright", options.get("timeout", 120), accepted=(0, 1)
    )
    data = json.loads(log.read_text())
    if data["summary"]["filesAnalyzed"] == 0:
        raise CheckError("Pyright 没有分析文件")
    issues = [
        finding(
            item["file"],
            item["range"]["start"]["line"] + 1,
            item.get("rule", "PYRIGHT"),
            item["message"],
        )
        for item in data["generalDiagnostics"]
        if item["severity"] in {"error", "warning"}
    ]
    return dict(
        status="fail" if issues else "pass",
        findings=issues,
        evidence=save(output, "pyright", data),
        scope="Pyright 静态类型分析；动态库的缺失存根作为诊断保留",
    )


def dependencies(root, files, options, output):
    """按显式禁止规则检查 Python 导入和 C++ include，不自动认可现有依赖。"""
    rules = options.get("forbidden", [])
    include_rules = options.get("include_forbidden", [])
    if not rules and not include_rules:
        raise CheckError("未配置 forbidden 或 include_forbidden 依赖规则")
    roots = [inside(root, name) for name in options.get("module_roots", ["."])]
    issues = []
    edges = []
    for name, language in files.items():
        path = root / name
        if language == "python":
            base = next((base for base in roots if path.is_relative_to(base)), None)
            if base is None:
                continue
            parts = path.relative_to(base).with_suffix("").parts
            module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            package = module if parts[-1] == "__init__" else module.rpartition(".")[0]
            for node in ast.walk(ast.parse(path.read_text())):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    prefix = node.module or ""
                    if node.level:
                        try:
                            prefix = importlib.util.resolve_name(
                                "." * node.level + prefix, package
                            )
                        except (ValueError, ImportError) as exc:
                            raise CheckError(f"{name}:{node.lineno}: {exc}") from exc
                    names = [prefix] + [prefix + "." + a.name for a in node.names]
                for target in names:
                    edges.append(
                        dict(source=module, target=target, file=name, line=node.lineno)
                    )
                    for rule in rules:
                        if prefix_matches(module, rule["from"]) and prefix_matches(
                            target, rule["to"]
                        ):
                            issues.append(
                                finding(
                                    name,
                                    node.lineno,
                                    "DEPENDENCY",
                                    f"{module} 不允许依赖 {target}",
                                )
                            )
        elif language == "cpp":
            for line, text in enumerate(path.read_text().splitlines(), 1):
                match = re.match(r'\s*#\s*include\s*[<"]([^>"]+)', text)
                if match:
                    for rule in include_rules:
                        if name.startswith(rule["from"]) and match[1].startswith(
                            rule["to"]
                        ):
                            issues.append(
                                finding(
                                    name,
                                    line,
                                    "DEPENDENCY",
                                    f"不允许 include {match[1]}",
                                )
                            )
    return dict(
        status="fail" if issues else "pass",
        findings=issues,
        evidence=save(output, "dependencies", edges),
        scope="显式禁止的静态导入/include；动态加载与职责合理性仍需审查",
    )


def prefix_matches(name, prefix):
    """只匹配完整模块边界，不将 core_extra 当作 core。"""
    return name == prefix or name.startswith(prefix + ".")


def security(root, files, options, output):
    """用 Bandit 扫描 Python 安全模式，保留问题而不自动修复。"""
    names = selected_files(root, files, options, "python")
    path = output / "bandit.json"
    run(
        [
            tool("bandit"),
            "-f",
            "json",
            "-o",
            str(path),
            *[str(root / name) for name in names],
        ],
        root,
        output,
        "bandit",
        accepted=(0, 1),
    )
    data = json.loads(path.read_text())
    if data.get("errors"):
        raise CheckError(f'Bandit 有扫描错误：{data["errors"]}')
    issues = [
        finding(
            item["filename"], item["line_number"], item["test_id"], item["issue_text"]
        )
        for item in data["results"]
    ]
    return dict(
        status="fail" if issues else "pass",
        findings=issues,
        evidence=str(path),
        scope="Bandit Python 模式检测；候选需审查，不代表完整安全审计",
    )


def secrets(root, files, options, output):
    """本地扫描指定文本范围中的凭据，报告仅保存类型与位置，不保存密钥值。"""
    from detect_secrets import SecretsCollection
    from detect_secrets.settings import default_settings

    paths = options.get("paths")
    if not paths:
        raise CheckError("secrets 须明确 paths，建议包含源码、配置和工作流")
    collection = SecretsCollection()
    scanned = []
    skipped = []
    with default_settings() as settings:
        settings.disable_filters(
            "detect_secrets.filters.common.is_ignored_due_to_verification_policies"
        )
        for name in paths:
            base = inside(root, name)
            for path in [base] if base.is_file() else walk(base):
                if path.is_symlink():
                    continue
                if path.stat().st_size > options.get("max_bytes", 1048576):
                    skipped.append(str(path.relative_to(root)))
                    continue
                try:
                    path.read_text(encoding="utf-8")
                except UnicodeError:
                    continue
                collection.scan_file(str(path))
                scanned.append(str(path.relative_to(root)))
    issues = [
        finding(
            secret.filename,
            secret.line_number,
            "SECRET",
            f"疑似凭据类型：{secret.type}；值已隐藏",
        )
        for _, secret in collection
    ]
    if not scanned:
        raise CheckError("凭据扫描没有文本输入")
    return dict(
        status="error" if skipped else "fail" if issues else "pass",
        findings=issues,
        scanned=scanned,
        skipped=skipped,
        reason="有超出大小限制的文件未扫描" if skipped else "",
        scope="当前文本工作区，不扫描 Git 历史；可能有误报或漏报",
    )


def vulnerabilities(root, files, options, output):
    """审计明确固定版本的 Python 依赖清单，网络或解析失败不能算通过。"""
    lock = inside(root, options["requirements"])
    lines = [
        line.strip()
        for line in lock.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not lines or any(
        not re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", line) for line in lines
    ):
        raise CheckError(
            "依赖审计须提供纯 name==version 的完整锁定清单，不执行安装脚本"
        )
    path = output / "pip-audit.json"
    run(
        [
            tool("pip-audit"),
            "--disable-pip",
            "--no-deps",
            "-r",
            str(lock),
            "-f",
            "json",
            "-o",
            str(path),
        ],
        root,
        output,
        "pip-audit",
        options.get("timeout", 120),
        accepted=(0, 1),
    )
    data = json.loads(path.read_text())
    deps = data["dependencies"]
    if len(deps) != len(lines) or any("skip_reason" in d for d in deps):
        raise CheckError("部分依赖没有完成漏洞查询")
    issues = [
        finding(
            str(lock),
            1,
            v["id"],
            f'{d["name"]}=={d["version"]} 已知漏洞；可用修复版本 {v.get("fix_versions",[])}',
        )
        for d in deps
        for v in d.get("vulns", [])
    ]
    return dict(
        status="fail" if issues else "pass",
        findings=issues,
        evidence=str(path),
        scope="仅清单中的 Python 包已知漏洞；不覆盖 ROS/系统包与未知漏洞",
    )
