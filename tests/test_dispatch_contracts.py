"""检查调度和全范围配置的防遗漏验证。"""

from pathlib import Path
from types import SimpleNamespace
import tomllib

import pytest

from code_supervisor import adapters, config
from code_supervisor.tasks import CheckError


def test_all_runtime_modules_are_mutation_inputs():
    """新增核心模块或 Python 工具脚本时必须同步进入 deep 范围。"""
    root = Path(__file__).resolve().parents[1]
    cfg = tomllib.loads((root / "supervisor.toml").read_text())
    expected = {
        str(p.relative_to(root))
        for folder in ["src/code_supervisor", "scripts"]
        for p in (root / folder).glob("*.py")
    }
    assert set(cfg["settings"]["mutator"]["files"]) == expected
    assert "mutator" in cfg["checks"] and "mutator" in cfg["required"]["deep"]


@pytest.mark.parametrize(
    "name,language,profile,enabled,raises,status",
    [
        ("pyright", "python", "quick", True, False, "not-run"),
        ("pyright", "cpp", "full", True, False, "not-applicable"),
        ("crapper", "python", "full", False, False, "not-run"),
        ("pyright", "python", "full", True, False, "pass"),
        ("pyright", "python", "full", True, True, "error"),
        ("cpp-thread", "cpp", "deep", True, False, "pass"),
    ],
)
def test_advanced_dispatch(
    tmp_path, monkeypatch, name, language, profile, enabled, raises, status
):
    """模式、语言和授权均生效，回调异常保留为执行错误。

    Args:
        tmp_path: 独立证据目录。
        monkeypatch: 适配器导入替换器。
        name: 检查器标识。
        language: 扫描到的源码语言。
        profile: 本次执行模式。
        enabled: 是否允许项目代码执行。
        raises: 回调是否模拟错误。
        status: 预期结果状态。
    """
    invoked = []

    def callback(root, files, options, output):
        """记录真实调度参数并返回指定结果。

        Args:
            root: 工程根目录。
            files: 扫描文件映射。
            options: 当前检查配置。
            output: 证据目录。
        """
        invoked.append(options)
        assert output == tmp_path / name and output.is_dir()
        if raises:
            raise CheckError("工具失败")
        return dict(status="pass", findings=[])

    def import_module(path):
        """返回受控的检测器模块。

        Args:
            path: 模块导入路径。
        """
        assert path == "code_supervisor." + adapters.REGISTRY[name][0]
        return SimpleNamespace(**{adapters.REGISTRY[name][1]: callback})

    monkeypatch.setattr(
        adapters, "importlib", SimpleNamespace(import_module=import_module)
    )
    cfg = dict(checks=["python-docs", name], settings={name: {}})
    rows = adapters.advanced_checks(
        tmp_path, cfg, {"a": language}, tmp_path, profile, enabled
    )
    assert len(rows) == 1 and rows[0]["status"] == status
    assert rows[0]["selected"] == (profile != "quick")
    assert bool(invoked) == (status in {"pass", "error"})
    assert cfg["settings"][name] == {}
    if name == "cpp-thread":
        assert invoked == [{"kind": "thread"}]
    if raises:
        assert rows[0]["reason"] == "CheckError: 工具失败"


def test_settings_accept_valid_dependency_rules():
    """合法依赖规则不可被过度校验拒绝，缺字段或非字符串仍被拒绝。"""
    adapters.validate_settings(
        {"dependencies": {"forbidden": [{"from": "core", "to": "ui"}]}}
    )
    for rule in [
        {},
        {"from": "core"},
        {"from": "core", "to": "ui", "extra": "x"},
        "bad",
        {"from": 1, "to": "ui"},
    ]:
        with pytest.raises(ValueError):
            adapters.validate_settings({"dependencies": {"forbidden": [rule]}})


def test_config_version_bool_and_explicit_symlink(tmp_path):
    """布尔值不能冒充版本号，显式文件链接不绕过源码扫描排除规则。

    Args:
        tmp_path: 独立配置和链接目录。
    """
    p = tmp_path / "supervisor.toml"
    p.write_text("version=true\n")
    with pytest.raises(ValueError):
        config.load(tmp_path, p)
    (tmp_path / "a.py").write_text("")
    (tmp_path / "link.py").symlink_to(tmp_path / "a.py")
    assert config.discover(tmp_path, dict(source=["link.py"], exclude=[])) == {}
