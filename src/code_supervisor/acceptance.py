"""业务、性质测试与性能验收的结构化报告协议。"""

import json
import math

from .checks import finding
from .config import inside
from .tasks import CheckError, argv, run, save, snapshot


def acceptance(root, files, options, output):
    """在隔离副本运行项目验收，读取本轮新生成的布尔检查与数值指标。

    Args:
        root: 工程根目录。
        files: 本次源码清单，由入口记录快照。
        options: inputs、argv、report 必填；limits 可设数值最大值门槛。
        output: 本次证据目录。

    Returns:
        每项检查均为布尔值且全部为真时通过；性能指标必须有限并满足门槛。

    Raises:
        CheckError: 报告为空、陈旧、类型不符或命令执行错误。
    """
    work = snapshot(root, output, options)
    path = inside(work, options["report"])
    if path.exists():
        raise CheckError("副本已含验收报告，拒绝将旧结果当作本次证据")
    command = argv(options, "argv", {"{workspace}": str(work), "{report}": str(path)})
    _, code = run(
        command,
        work,
        output,
        "acceptance",
        options.get("timeout", 300),
        accepted=(0, 1),
    )
    data = json.loads(path.read_text())
    checks = data.get("checks")
    if (
        not isinstance(checks, dict)
        or not checks
        or any(type(v) is not bool for v in checks.values())
    ):
        raise CheckError("验收 report.checks 必须是非空布尔映射")
    issues = [
        finding("", 1, "ACCEPTANCE", name + " 未通过")
        for name, value in checks.items()
        if not value
    ]
    for name, limit in options.get("limits", {}).items():
        value = data.get("metrics", {}).get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise CheckError(f"验收指标缺失或非有限：{name}")
        if value > limit:
            issues.append(finding("", 1, "PERFORMANCE", f"{name}={value} 超过 {limit}"))
    if code and not issues:
        raise CheckError("验收命令失败但报告声称全部通过")
    return dict(
        status="fail" if issues else "pass",
        findings=issues,
        evidence=save(output, "acceptance", data),
        scope="项目定义的业务、性质或性能判据；不能自动推断物理模型是否真实",
    )
