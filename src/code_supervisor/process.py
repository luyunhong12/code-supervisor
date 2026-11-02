"""在独立进程组执行检查命令，保存输出并限制运行时间。"""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def execute(argv, cwd, log, timeout=120, finding_codes=(1,)):
    """执行可信配置中的 argv，不通过 shell 解释。

    命令可以产生自身副作用；调用方必须先获得执行配置命令的明确意图。
    Linux 超时会杀死本次进程组；主动脱离进程组的守护进程不受此保证。

    Args:
        argv: 程序及参数列表，首项 {python} 可替换为当前解释器。
        cwd: 子进程工作目录。
        log: 标准输出及错误合并写入的文件路径。
        timeout: 最大等待秒数，必须为正。
        finding_codes: 表示检查发现问题的非零退出码，其余非零码视为执行错误。

    Returns:
        包含状态、命令、退出码（如有）、耗时和日志位置的字典。
    """
    argv = [sys.executable if a == "{python}" else a for a in argv]
    result = {"command": argv, "log": str(log)}
    start = time.monotonic()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        with Path(log).open("wb") as output:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                code = proc.wait(timeout=timeout)
                result.update(
                    returncode=code,
                    status=(
                        "pass"
                        if code == 0
                        else "fail" if code in finding_codes else "error"
                    ),
                )
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                if isinstance(exc, KeyboardInterrupt):
                    raise
                result.update(status="error", reason=f"超过 {timeout} 秒，已终止进程组")
    except OSError as exc:
        result.update(status="error", reason=str(exc))
    result["seconds"] = round(time.monotonic() - start, 3)
    return result
