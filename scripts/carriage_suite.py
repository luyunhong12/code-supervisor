"""在已复制的车辆工程中构建并运行其原有验收，转换为督导协议。"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def convert_summary(data):
    """只接受完整、非空且状态一致的车辆验收汇总。"""
    results = data.get("results")
    if data.get("complete") is not True or not isinstance(results, dict) or not results:
        raise ValueError("车辆验收未完整结束或没有工况")
    if any(
        not isinstance(v, dict) or type(v.get("passed")) is not bool
        for v in results.values()
    ):
        raise ValueError("车辆验收工况缺少布尔 passed")
    checks = {name: row["passed"] for name, row in results.items()}
    if type(data.get("passed")) is not bool or data["passed"] != all(checks.values()):
        raise ValueError("车辆验收总状态与工况状态矛盾")
    return dict(checks=checks, source_run_id=data.get("run_id"))


def main():
    """只在标记过的独立副本构建；直接调用车辆工程已有的物理判据。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=("code", "baseline", "experimental"))
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    root = Path.cwd()
    if not (root / "supervisor-copy.json").is_file():
        raise ValueError("仅允许在 prepare_carriage.py 创建的副本执行")
    output = root / ".generated/carriage-acceptance"
    if output.exists():
        raise ValueError("拒绝复用旧验收输出目录")
    # 固定 shell 程序；用户路径仅作为位置参数传入，不拼接到 shell 源码。
    command = [
        "bash",
        "-c",
        'set -e; source /opt/ros/jazzy/setup.bash; colcon build --executor sequential; source install/setup.bash; exec /usr/bin/python3 tools/validate_project.py --suite "$1" --output-root "$2"',
        "carriage-suite",
        args.suite,
        str(output),
    ]
    env = dict(os.environ)
    for key in (
        "PYTHONPATH",
        "AMENT_PREFIX_PATH",
        "CMAKE_PREFIX_PATH",
        "COLCON_PREFIX_PATH",
        "LD_LIBRARY_PATH",
        "ROS_PACKAGE_PATH",
    ):
        env.pop(key, None)
    done = subprocess.run(command, cwd=root, env=env, check=False)
    summaries = list(output.glob("*/summary.json"))
    if len(summaries) != 1:
        raise ValueError("构建失败或未得到唯一的本轮汇总")
    report = convert_summary(json.loads(summaries[0].read_text()))
    if done.returncode and all(report["checks"].values()):
        raise ValueError("执行失败但报告声称全部通过")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return int(not all(report["checks"].values()))


if __name__ == "__main__":
    sys.exit(main())
