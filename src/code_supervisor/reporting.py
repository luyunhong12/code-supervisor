"""可移植报告、历史差异与运行环境诊断。"""

from collections import Counter, defaultdict
import importlib.metadata
import json
from pathlib import Path
from urllib.parse import quote

from .tasks import CheckError, tool


def issue_key(check, issue):
    """按检查器、路径、规则和消息识别诊断；行号变化不制造新问题。

    Args:
        check: 诊断所属的检查器标识。
        issue: 含文件、规则、消息和行号的诊断映射。
    """
    return (check, issue["file"], issue["rule"], issue["message"])


def issue_groups(report):
    """按稳定诊断键分组，保留同类诊断的全部出现次数。

    Args:
        report: 包含各检查器诊断的报告映射。
    """
    groups = defaultdict(list)
    for row in report["results"]:
        for issue in row.get("findings", []):
            groups[issue_key(row["id"], issue)].append(issue)
    return groups


def unmatched_occurrences(before, after):
    """优先匹配同一行的出现次数，再将剩余配对视为行号移动。

    同类诊断没有定义级标识时无法证明具体哪个对象被修复；返回位置供人工复核。

    Args:
        before: 同一诊断键在一份报告中的全部出现项。
        after: 另一份报告中同一诊断键的全部出现项。
    """
    lines = Counter(issue["line"] for issue in after)
    unmatched = []
    for issue in before:
        if lines[issue["line"]]:
            lines[issue["line"]] -= 1
        else:
            unmatched.append(issue)
    moved = min(len(unmatched), sum(lines.values()))
    return unmatched[moved:]


def valid_snapshot(report):
    """只有明确标记未变化且没有快照错误的报告才可验证诊断消失。

    Args:
        report: 待核对快照有效性的报告。
    """
    return report.get("source_unchanged") is True and not any(
        row["id"] == "snapshot" and row["status"] != "pass" for row in report["results"]
    )


def configuration_scope(results):
    """读取参数检查实际扫描的配置清单，缺少证据时保守返回未知。

    Args:
        results: 按检查器名称索引的报告结果。
    """
    row = results.get("parameter-docs")
    if row is None:
        return []
    names = row.get("configuration_files")
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        return None
    return sorted(names)


def compare_reports(before, after):
    """比较同项目有效报告的诊断次数，未知身份或无效快照只保留待验证项。

    Args:
        before: 较早一次检查的完整报告映射。
        after: 较新一次检查的完整报告映射。
    """
    old, new = issue_groups(before), issue_groups(after)
    previous = {row["id"]: row for row in before["results"]}
    current = {row["id"]: row for row in after["results"]}
    scope_changed = not before.get("root") or any(
        before.get(field) is None or before.get(field) != after.get(field)
        for field in ("root", "files", "config_sha256")
    )
    old_configs, new_configs = configuration_scope(previous), configuration_scope(
        current
    )
    # 双方都未知时不能视为相同；单方未知已由不相等覆盖。
    scope_changed |= old_configs is None or old_configs != new_configs
    snapshots_valid = valid_snapshot(before) and valid_snapshot(after)
    added, resolved, unverified = [], [], []
    for key in sorted(old.keys() | new.keys()):
        prior, latest = old.get(key, []), new.get(key, [])
        added.extend(unmatched_occurrences(latest, prior))
        missing = unmatched_occurrences(prior, latest)
        check = current.get(key[0], {})
        verified = (
            check.get("status") in {"pass", "fail"}
            and check.get("selected", True)
            and not scope_changed
            and snapshots_valid
        )
        (resolved if verified else unverified).extend(missing)
    return dict(
        added=added,
        resolved=resolved,
        unverified=unverified,
        statuses=[
            dict(
                id=name,
                before=previous.get(name, {}).get("status"),
                after=current.get(name, {}).get("status"),
            )
            for name in sorted(previous.keys() | current.keys())
            if previous.get(name, {}).get("status")
            != current.get(name, {}).get("status")
        ],
        scope_changed=scope_changed,
        note="差异按诊断次数比较；项目或范围不一致、快照无效及检查未完成时归入unverified。行号移动配对及具体修复对象仍需复核。",
    )


def sarif(report):
    """转换带位置诊断为 SARIF，另以通知保留错误和未执行项。

    Args:
        report: 包含检查结果、范围和运行元信息的报告映射。
    """
    results, notifications = [], []
    root = Path(report["root"])
    for row in report["results"]:
        if row["status"] in {"error", "not-run"}:
            notifications.append(
                dict(
                    level="error" if row.get("selected", True) else "note",
                    message=dict(
                        text=row["id"] + ": " + row.get("reason", row["status"])
                    ),
                )
            )
        for issue in row.get("findings", []):
            result = dict(
                ruleId=row["id"] + "/" + issue["rule"],
                level="warning",
                message=dict(text=issue["message"]),
            )
            name = issue["file"]
            if name:
                path = Path(name)
                if path.is_absolute() and path.is_relative_to(root):
                    name = str(path.relative_to(root))
                uri = Path(name).as_uri() if Path(name).is_absolute() else quote(name)
                result["locations"] = [
                    dict(
                        physicalLocation=dict(
                            artifactLocation=dict(uri=uri),
                            region=dict(startLine=max(1, int(issue["line"]))),
                        )
                    )
                ]
            results.append(result)
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            dict(
                tool=dict(
                    driver=dict(name="code-supervisor", version=report["version"])
                ),
                results=results,
                invocations=[
                    dict(
                        executionSuccessful=report["exit_code"] != 2,
                        toolExecutionNotifications=notifications,
                    )
                ],
            )
        ],
    }


def doctor(language="all"):
    """按语言列出工具和包是否可发现，不冒充真实功能测试。

    Args:
        language: python、cpp 或 all；仅要求所选工具链。
    """
    rows = []
    executables = {
        "python": ("pyright", "bandit", "pip-audit"),
        "cpp": (
            "cmake",
            "ctest",
            "g++",
            "gcov",
            "doxygen",
            "clang-tidy",
            "gcovr",
            "jscpd",
            "node",
        ),
    }
    packages = {
        "python": (
            "crapper",
            "dryer",
            "mutator",
            "coverage",
            "detect-secrets",
            "hypothesis",
        ),
        "cpp": ("lizard", "tree-sitter", "tree-sitter-cpp"),
    }
    groups = ("python", "cpp") if language == "all" else (language,)
    for name in dict.fromkeys(name for group in groups for name in executables[group]):
        try:
            rows.append(dict(tool=name, path=tool(name), available=True))
        except CheckError:
            rows.append(dict(tool=name, available=False))
    for name in dict.fromkeys(name for group in groups for name in packages[group]):
        try:
            rows.append(
                dict(
                    tool=name, version=importlib.metadata.version(name), available=True
                )
            )
        except importlib.metadata.PackageNotFoundError:
            rows.append(dict(tool=name, available=False))
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0 if all(row["available"] for row in rows) else 2
