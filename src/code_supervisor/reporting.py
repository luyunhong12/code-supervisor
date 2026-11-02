"""可移植报告、历史差异与运行环境诊断。"""

import importlib.metadata
import json
from pathlib import Path
from urllib.parse import quote

from .tasks import CheckError, tool


def issue_key(check, issue):
    """按检查器、路径、规则和消息识别诊断；行号变化不制造新问题。"""
    return (check, issue["file"], issue["rule"], issue["message"])


def compare_reports(before, after):
    """比较两次机器报告，保留状态退化，不自动豁免历史问题。"""

    def entries(report):
        """建立诊断索引。"""
        return {
            issue_key(row["id"], issue): issue
            for row in report["results"]
            for issue in row.get("findings", [])
        }

    old, new = entries(before), entries(after)
    statuses = {row["id"]: row["status"] for row in before["results"]}
    return dict(
        added=[new[key] for key in sorted(new.keys() - old.keys())],
        resolved=[old[key] for key in sorted(old.keys() - new.keys())],
        statuses=[
            dict(id=row["id"], before=statuses.get(row["id"]), after=row["status"])
            for row in after["results"]
            if statuses.get(row["id"]) != row["status"]
        ],
        scope_changed=before.get("files") != after.get("files")
        or before.get("config_sha256") != after.get("config_sha256"),
        note="差异只辅助复查；退出状态以本次完整报告为准，移出检查范围不代表修复。",
    )


def sarif(report):
    """转换带位置诊断为 SARIF，另以通知保留错误和未执行项。"""
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


def doctor():
    """列出高级工具和 Python 包是否可发现；不冒充真实功能测试。"""
    rows = []
    for name in (
        "cmake",
        "ctest",
        "g++",
        "gcov",
        "doxygen",
        "clang-tidy",
        "gcovr",
        "jscpd",
        "pyright",
        "bandit",
        "pip-audit",
        "node",
    ):
        try:
            rows.append(dict(tool=name, path=tool(name), available=True))
        except CheckError:
            rows.append(dict(tool=name, available=False))
    for name in (
        "crapper",
        "dryer",
        "mutator",
        "coverage",
        "detect-secrets",
        "lizard",
        "hypothesis",
    ):
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
