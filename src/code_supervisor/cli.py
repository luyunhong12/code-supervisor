"""统一命令行入口，保存检查证据并明确未完成的范围。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

from . import __version__
from .adapters import REGISTRY, advanced_checks
from .checks import black_check, python_docs, ruff_check
from .config import discover, load
from .cpp import cpp_docs
from .process import execute
from .reporting import compare_reports, doctor, sarif

TEMPLATE = """version = 1
name = "my-project"
source = ["."]
exclude = []
checks = ["python-docs", "black", "ruff", "cpp-docs"]
policy = []

[required]
full = ["tests"]
deep = ["tests", "mutation"]

# 配置好实际命令后取消注释。只执行可信配置。
# [[commands]]
# id = "tests"
# argv = ["{python}", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
# profile = "full"
# timeout = 120
# finding_codes = [1]
"""
LABELS = {
    "pass": "通过",
    "fail": "发现问题",
    "error": "执行错误",
    "not-run": "未执行",
    "not-applicable": "不适用",
}


def fingerprints(root, files):
    """返回源码 SHA256；读取失败传播给调用方。"""
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files
    }


def git_metadata(root):
    """读取 Git 提交和工作区状态；非 Git 工程也可正常检查。"""
    result = {}
    for key, args in (
        ("head", ["rev-parse", "HEAD"]),
        ("status", ["status", "--porcelain"]),
    ):
        try:
            done = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                timeout=10,
            )
            result[key] = done.stdout.strip() if done.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            result[key] = None
    return result


def builtin_checks(root, cfg, files, output):
    """逐项执行内置检查；不适用或依赖缺失均显式记录。"""
    results = []
    for name in cfg["checks"]:
        if name in REGISTRY:
            continue
        language = "cpp" if name == "cpp-docs" else "python"
        selected = [f for f, lang in files.items() if lang == language]
        if not selected:
            result = {
                "status": "not-applicable",
                "reason": f"范围内没有 {language} 文件",
            }
        else:
            try:
                if name == "ruff":
                    result = ruff_check(root, selected, output)
                else:
                    callback = {
                        "black": black_check,
                        "python-docs": python_docs,
                        "cpp-docs": cpp_docs,
                    }[name]
                    result = callback(root, selected)
            except Exception as exc:
                result = {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}
        results.append(dict(result, id=name, files=selected))
    return results


def command_checks(root, cfg, profile, enabled, output):
    """按模式运行显式配置命令，未授权执行时仅记录未执行。"""
    order = {"quick": 0, "full": 1, "deep": 2}
    results = []
    for item in cfg["commands"]:
        selected = order[item.get("profile", "full")] <= order[profile]
        if not selected or not enabled:
            result = {
                "status": "not-run",
                "reason": (
                    "不属于本次模式"
                    if not selected
                    else "配置命令需要 --run-commands 才会执行"
                ),
            }
        else:
            result = execute(
                item["argv"],
                root,
                output / (item["id"] + ".log"),
                item["timeout"],
                item["finding_codes"],
            )
        results.append(dict(result, id=item["id"], selected=selected))
    return results


def outcome(results):
    """计算本次门禁退出码：0 已执行范围通过、1 问题、2 错误/不完整。"""
    selected = [r for r in results if r.get("selected", True)]
    if any(r["status"] in {"error", "not-run"} for r in selected):
        return 2
    return 1 if any(r["status"] == "fail" for r in selected) else 0


def write_report(output, report):
    """保存 JSON 与中文文本报告，不向终端输出配置命令的原始日志。"""
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "report.sarif").write_text(
        json.dumps(sarif(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "代码督导队检查报告",
        f"项目：{report['root']}",
        f"模式：{report['profile']}；文件数：{len(report['files'])}；退出码：{report['exit_code']}",
        "通过仅指本次已执行的规则子集，不是完整 Google/Doxygen 或业务正确性认证。",
        "",
    ]
    for result in report["results"]:
        lines.append(f"{result['id']}：{LABELS[result['status']]}")
        for key in ("reason", "scope"):
            if result.get(key):
                lines.append("  " + result[key])
        for issue in result.get("findings", []):
            lines.append(
                f"  {issue['file']}:{issue['line']} [{issue['rule']}] {issue['message']}"
            )
        if result.get("unparsed_files"):
            lines.append("  无法完整解析：" + ", ".join(result["unparsed_files"]))
    lines += [
        "",
        "人工审查：参数单位、契约真实性、架构职责、物理判据仍须人工/AI结合证据审查。",
        "高级检查以各项实际状态与证据为准；未执行的模式不计为通过。",
    ]
    (output / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def check(args):
    """执行一次检查并保存唯一报告；源码中途变化使本次证据失效。"""
    root = args.project.resolve()
    if not root.is_dir():
        raise ValueError("项目目录不存在")
    config = args.config.resolve() if args.config else root / "supervisor.toml"
    cfg = load(root, config)
    files = discover(root, cfg)
    if not files:
        raise ValueError("扫描范围内没有 Python/C++ 文件，拒绝空扫描通过")
    output_base = (
        args.output.resolve() if args.output else root / ".generated" / "supervisor"
    )
    output = output_base / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    output.mkdir(parents=True, exist_ok=False)
    before = fingerprints(root, files)
    report = dict(
        version=__version__,
        root=str(root),
        profile=args.profile,
        git=git_metadata(root),
        files=files,
        hashes=before,
        config=str(config),
        config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
        policy_hashes=fingerprints(root, cfg["policy"]),
    )
    results = builtin_checks(root, cfg, files, output)
    results.extend(command_checks(root, cfg, args.profile, args.run_commands, output))
    results.extend(
        advanced_checks(root, cfg, files, output, args.profile, args.run_commands)
    )
    for name in cfg["required"].get(args.profile, []):
        match = next((r for r in results if r["id"] == name), None)
        if match is None:
            results.append(
                dict(
                    id=name,
                    status="not-run",
                    reason="本模式要求该检查，但尚未配置适配命令",
                )
            )
        elif match["status"] == "not-run":
            match["selected"] = True
    try:
        changed = discover(root, cfg) != files or fingerprints(root, files) != before
        changed |= (
            hashlib.sha256(config.read_bytes()).hexdigest() != report["config_sha256"]
        )
        changed |= fingerprints(root, cfg["policy"]) != report["policy_hashes"]
    except OSError:
        changed = True
    if changed:
        results.append(
            dict(
                id="snapshot",
                status="error",
                reason="检查期间源码、配置或规范变化，结果不代表一致快照",
            )
        )
    report.update(
        results=results, exit_code=outcome(results), source_unchanged=not changed
    )
    write_report(output, report)
    for result in results:
        print(
            f"{result['id']}: {LABELS[result['status']]} ({len(result.get('findings', []))} 条诊断)"
        )
    print(f"报告：{output / 'report.txt'}")
    return report["exit_code"]


def main():
    """解析命令并返回退出码，配置错误给出简短说明。"""
    parser = argparse.ArgumentParser(
        description="代码督导队：无 AI 自动检查＋Markdown 审查流程"
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor", help="检查工具安装情况")
    diff = sub.add_parser("compare", help="比较两份历史报告，不隐藏已有问题")
    diff.add_argument("before", type=Path)
    diff.add_argument("after", type=Path)
    init = sub.add_parser("init", help="创建项目配置，不覆盖已有文件")
    init.add_argument("project", type=Path)
    run = sub.add_parser("check", help="检查源码并输出证据")
    run.add_argument("project", type=Path)
    run.add_argument("--config", type=Path)
    run.add_argument("--output", type=Path)
    run.add_argument("--profile", choices=("quick", "full", "deep"), default="quick")
    run.add_argument(
        "--run-commands",
        action="store_true",
        help="执行可信配置中的命令（测试/构建可能写生成物）",
    )
    args = parser.parse_args()
    try:
        if args.action == "doctor":
            return doctor()
        if args.action == "compare":
            print(
                json.dumps(
                    compare_reports(
                        json.loads(args.before.read_text()),
                        json.loads(args.after.read_text()),
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.action == "init":
            if not args.project.is_dir():
                raise ValueError("项目目录不存在")
            with (args.project / "supervisor.toml").open(
                "x", encoding="utf-8"
            ) as stream:
                stream.write(TEMPLATE)
            print("已创建 supervisor.toml，请确认扫描范围及测试命令。")
            return 0
        return check(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"配置或执行错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
