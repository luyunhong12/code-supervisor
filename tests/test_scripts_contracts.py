"""维护脚本的副本保护、验收状态与生成配置契约。"""

import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    """加载脚本而不执行其命令行入口。

    Args:
        name: scripts 目录中的脚本名称。
    """
    return runpy.run_path(str(ROOT / "scripts" / name))


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"complete": True, "results": {}},
        {"complete": True, "results": []},
        {"complete": False, "results": {"a": {"passed": True}}, "passed": True},
        {"complete": True, "results": {"a": True}, "passed": True},
        {"complete": True, "results": {"a": {"passed": 1}}, "passed": True},
        {"complete": True, "results": {"a": {"passed": True}}, "passed": 1},
        {"complete": True, "results": {"a": {"passed": False}}, "passed": True},
    ],
)
def test_carriage_summary_rejects_incomplete(data):
    """不完整、非布尔和矛盾结果不能转换为成功证据。

    Args:
        data: 无效的车辆汇总。
    """
    with pytest.raises(ValueError):
        script("carriage_suite.py")["convert_summary"](data)


@pytest.mark.parametrize(
    "code,passed,count,expected",
    [
        (0, True, 1, 0),
        (1, False, 1, 1),
        (1, True, 1, None),
        (0, True, 0, None),
        (0, True, 2, None),
    ],
)
def test_carriage_main_protocol(tmp_path, monkeypatch, code, passed, count, expected):
    """仅在副本执行，保留唯一汇总与退出码的一致性，不启动 ROS。

    Args:
        tmp_path: 独立副本目录。
        monkeypatch: 命令与环境替换器。
        code: 模拟构建验收退出码。
        passed: 模拟工况结果。
        count: 模拟汇总文件数量。
        expected: 预期返回值，None 表示拒绝结果。
    """
    module = script("carriage_suite.py")
    main = module["main"]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["carriage", "code", str(tmp_path / "result.json")])
    with pytest.raises(ValueError, match="仅允许"):
        main()
    (tmp_path / "supervisor-copy.json").write_text("{}")
    monkeypatch.setenv("PYTHONPATH", "must-not-leak")

    def run(command, **kwargs):
        """模拟构建结束后的输出目录。

        Args:
            command: 固定 shell 程序及位置参数。
            kwargs: 工作目录、环境与退出码处理选项。
        """
        assert command[:2] == ["bash", "-c"] and command[-2] == "code"
        assert kwargs["cwd"] == tmp_path and kwargs["check"] is False
        assert not set(kwargs["env"]) & {
            "PYTHONPATH",
            "AMENT_PREFIX_PATH",
            "CMAKE_PREFIX_PATH",
            "COLCON_PREFIX_PATH",
            "LD_LIBRARY_PATH",
            "ROS_PACKAGE_PATH",
        }
        for index in range(count):
            folder = tmp_path / ".generated/carriage-acceptance" / str(index)
            folder.mkdir(parents=True)
            (folder / "summary.json").write_text(
                json.dumps(
                    dict(
                        complete=True,
                        passed=passed,
                        results={"中文工况": {"passed": passed}},
                        run_id="run",
                    )
                )
            )
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(main.__globals__["subprocess"], "run", run)
    if expected is None:
        with pytest.raises(ValueError):
            main()
    else:
        assert main() == expected
        text = (tmp_path / "result.json").read_text()
        assert "中文工况" in text
        assert json.loads(text) == dict(
            checks={"中文工况": passed}, source_run_id="run"
        )
    folder = tmp_path / ".generated/carriage-acceptance"
    folder.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="旧验收"):
        main()


def test_prepare_creates_parent_and_refuses_overwrite(tmp_path, monkeypatch):
    """生成目录可包含新父目录；再次运行不得复用旧输出。

    Args:
        tmp_path: 输入工程和验收副本根目录。
        monkeypatch: 参数替换器。
    """
    import tomllib

    root = tmp_path / "project"
    for name in ["src/pkg/config", "tools", "model", "docs"]:
        (root / name).mkdir(parents=True)
    (root / "src/pkg/config/params.yaml").write_text("x: 1")
    (root / "src/pkg/node.py").write_text("")
    (root / "tools/check.py").write_text("")
    for name in ["pyproject.toml", "pytest.ini"]:
        (root / name).write_text("")
    output = tmp_path / "new/child"
    monkeypatch.setattr(
        "sys.argv", ["prepare", str(root), str(output), "--suite", "experimental"]
    )
    main = script("prepare_carriage.py")["main"]
    main()
    work = output / "workspace"
    cfg = tomllib.loads((work / "supervisor.toml").read_text())
    assert cfg["settings"]["parameter-docs"]["paths"] == ["src/pkg/config"]
    assert cfg["settings"]["dryer"]["files"] == ["src/pkg/node.py", "tools/check.py"]
    assert cfg["settings"]["acceptance"]["argv"][-2] == "experimental"
    cfg = tomllib.loads((work / "supervisor-brake.toml").read_text())
    for name in [
        "cpp-build",
        "clang-tidy",
        "cpp-coverage",
        "cpp-sanitizers",
        "cpp-mutation",
    ]:
        assert cfg["settings"][name]["cmake_source"] == "supervisor-native"
    assert cfg["settings"]["cpp-mutation"]["max_mutants"] == 200
    assert cfg["settings"]["cpp-coverage"]["files"] == [
        "src/carriage_control/native/brake_law.hh"
    ]
    with pytest.raises(FileExistsError):
        main()
