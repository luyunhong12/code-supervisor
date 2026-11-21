"""安装分组只调度所选工具链，验证时不联网或安装软件。"""

import os
from pathlib import Path
import shutil
import subprocess
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", ["python", "cpp", "all"])
def test_bootstrap_language_dispatch(tmp_path, mode):
    """用记录参数的可执行文件验证安装分支，不执行真实 pip/npm。

    Args:
        tmp_path: pytest 提供的独立脚本与工具目录。
        mode: 选择的安装模式。
    """
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "tools").mkdir()
    shutil.copy2(ROOT / "scripts/bootstrap.sh", project / "scripts/bootstrap.sh")
    for name in ("package.json", "package-lock.json"):
        (project / "tools" / name).write_text("{}")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "calls"
    recorder = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$INSTALL_TEST_LOG"\n'
    for name in ("python3", "npm"):
        path = binaries / name
        path.write_text(recorder)
        path.chmod(0o755)
    # 模拟 venv 已就绪，让 Python stub 只记录 pip/解析器调用。
    (project / ".venv/bin").mkdir(parents=True)
    for name in ("python", "supervisor"):
        path = project / ".venv/bin" / name
        path.write_text(recorder)
        path.chmod(0o755)
    env = dict(
        os.environ,
        PATH=str(binaries) + os.pathsep + os.environ["PATH"],
        INSTALL_TEST_LOG=str(log),
    )
    done = subprocess.run(
        ["bash", str(project / "scripts/bootstrap.sh"), mode],
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    calls = log.read_text()
    assert f"doctor --language {mode}" in calls
    assert ("ci --prefix .tools" in calls) == (mode != "python")
    assert ("requirements-ub.txt" in calls) == (mode != "cpp")
    assert f".[{'quality' if mode == 'all' else mode}]" in calls


def test_bootstrap_rejects_invalid_mode(tmp_path):
    """无效模式在创建环境或安装前返回错误。

    Args:
        tmp_path: pytest 提供的独立脚本目录。
    """
    (tmp_path / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts/bootstrap.sh", tmp_path / "scripts/bootstrap.sh")
    done = subprocess.run(
        ["bash", str(tmp_path / "scripts/bootstrap.sh"), "java"],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 2
    assert not (tmp_path / ".venv").exists()


def test_optional_dependencies_cover_both_languages():
    """兼容的完整安装组包含两种语言组的全部直接依赖。"""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    groups = config["project"]["optional-dependencies"]
    assert set(groups["python"]) | set(groups["cpp"]) <= set(groups["quality"])
    assert "PyYAML==6.0.3" in config["project"]["dependencies"]
