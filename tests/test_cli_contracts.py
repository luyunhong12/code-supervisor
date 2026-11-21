"""命令行入口与配置门禁的直接契约验证。"""

import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from code_supervisor import cli, config, adapters


def invoke(monkeypatch, *arguments):
    """在当前解释器调用真实命令行入口。

    Args:
        monkeypatch: pytest 参数替换工具。
        arguments: 命令行参数。
    """
    monkeypatch.setattr("sys.argv", ["supervisor", *map(str, arguments)])
    return cli.main()


def test_cli_init_check_compare_errors(tmp_path, monkeypatch, capsys):
    """初始化不覆盖文件，检查写出证据，报告比较保留中文，错误返回2。

    Args:
        tmp_path: 独立工程目录。
        monkeypatch: 命令行参数替换工具。
        capsys: 标准输出捕获工具。
    """
    assert invoke(monkeypatch, "init", tmp_path) == 0
    template = (tmp_path / "supervisor.toml").read_text()
    assert invoke(monkeypatch, "init", tmp_path) == 2
    assert (tmp_path / "supervisor.toml").read_text() == template
    assert invoke(monkeypatch, "init", tmp_path / "missing") == 2
    assert invoke(monkeypatch, "check", tmp_path / "missing") == 2
    (tmp_path / "supervisor.toml").write_text(
        'version=1\nsource=["."]\nchecks=["python-docs","black","ruff","cpp-docs","parameter-docs"]\n[settings.parameter-docs]\npaths=[]\n'
    )
    (tmp_path / "a.py").write_text('"""中文模块。"""\n')
    assert invoke(monkeypatch, "check", tmp_path) == 0
    path = next((tmp_path / ".generated/supervisor").glob("*/report.json"))
    report = json.loads(path.read_text())
    assert report["source_unchanged"] is True
    assert report["files"] == {"a.py": "python"}
    assert report["hashes"] == {
        "a.py": hashlib.sha256((tmp_path / "a.py").read_bytes()).hexdigest()
    }
    assert (
        next(row for row in report["results"] if row["id"] == "cpp-docs")["status"]
        == "not-applicable"
    )
    capsys.readouterr()
    assert invoke(monkeypatch, "compare", path, path) == 0
    text = capsys.readouterr().out
    assert "差异" in text
    assert json.loads(text)["resolved"] == []
    assert invoke(monkeypatch, "compare", path, tmp_path / "absent.json") == 2
    (tmp_path / "a.py").write_text("def missing(x): pass\n")
    assert invoke(monkeypatch, "check", tmp_path) == 1


def test_cli_command_profiles_and_required(tmp_path, monkeypatch):
    """模式、执行授权及 required 联合决定退出状态。

    Args:
        tmp_path: 独立工程目录。
        monkeypatch: 命令行参数替换工具。
    """
    (tmp_path / "a.py").write_text('"""模块。"""\n')
    cfg = tmp_path / "supervisor.toml"
    cfg.write_text(
        'version=1\nchecks=["python-docs"]\n[required]\nquick=["later"]\n[[commands]]\nid="later"\nprofile="deep"\nargv=["{python}","-c","pass"]\n'
    )
    assert invoke(monkeypatch, "check", tmp_path) == 2
    cfg.write_text(
        'version=1\nchecks=["python-docs"]\n[[commands]]\nid="tests"\nprofile="full"\nargv=["{python}","-c","pass"]\n'
    )
    assert invoke(monkeypatch, "check", tmp_path) == 0
    assert invoke(monkeypatch, "check", tmp_path, "--profile", "full") == 2
    assert (
        invoke(monkeypatch, "check", tmp_path, "--profile", "full", "--run-commands")
        == 0
    )
    cfg.write_text('version=1\nchecks=["python-docs"]\n[required]\nfull=["missing"]\n')
    assert invoke(monkeypatch, "check", tmp_path, "--profile", "full") == 2


@pytest.mark.parametrize(
    "status,expected",
    [("pass", 0), ("fail", 1), ("error", 2), ("not-run", 2), ("not-applicable", 0)],
)
def test_outcome_priority(status, expected):
    """门禁保留错误优先级且不统计未选检查。

    Args:
        status: 被选择检查的状态。
        expected: 对应退出码。
    """
    assert cli.outcome([dict(status=status)]) == expected
    assert cli.outcome([dict(status=status, selected=False)]) == 0
    assert cli.outcome([dict(status="fail"), dict(status="error")]) == 2


def test_cli_builtin_errors_and_doctor(tmp_path, monkeypatch):
    """检测器异常形成可读错误，doctor 按参数转发。

    Args:
        tmp_path: 独立工程目录。
        monkeypatch: 替换失败检测器。
    """

    def broken(root, files):
        """模拟无法获得检查证据。

        Args:
            root: 检查根目录。
            files: 选中的源码文件。
        """
        raise ValueError("解析失败")

    def environment(language):
        """验证环境查询的语言选择。

        Args:
            language: 用户选择的工具链。
        """
        assert language == "cpp"
        return 2

    monkeypatch.setattr(cli, "python_docs", broken)
    result = cli.builtin_checks(
        tmp_path, {"checks": ["python-docs", "mutator"]}, {"a.py": "python"}, tmp_path
    )
    assert len(result) == 1 and result[0]["status"] == "error"
    assert result[0]["reason"] == "ValueError: 解析失败"
    monkeypatch.setattr(cli, "doctor", environment)
    assert invoke(monkeypatch, "doctor", "--language", "cpp") == 2


@pytest.mark.parametrize("failure", [None, "code", "os", "timeout"])
def test_git_metadata_failure_handling(tmp_path, monkeypatch, failure):
    """Git 元信息失败不阻断检查，成功时去掉输出空白。

    Args:
        tmp_path: 模拟工程目录。
        monkeypatch: 替换 Git 调用。
        failure: 模拟执行结果或异常。
    """

    def run(command, **kwargs):
        """返回可预测的 Git 执行结果。

        Args:
            command: Git 命令参数。
            kwargs: 进程运行选项。
        """
        assert command[:3] == ["git", "-C", str(tmp_path)]
        assert kwargs == dict(capture_output=True, text=True, timeout=10)
        if failure == "os":
            raise OSError("无法运行")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 10)
        return SimpleNamespace(
            returncode=1 if failure == "code" else 0, stdout="  中文  \n"
        )

    monkeypatch.setattr(cli.subprocess, "run", run)
    expected = "中文" if failure is None else None
    assert cli.git_metadata(tmp_path) == dict(head=expected, status=expected)


def test_config_defaults_and_command_limits(tmp_path):
    """默认配置和合法边界不被误拒，命令参数的非法边界明确拒绝。

    Args:
        tmp_path: 独立配置目录。
    """
    p = tmp_path / "supervisor.toml"
    p.write_text("version=1\n")
    cfg = config.load(tmp_path, p)
    assert cfg["source"] == ["."] and set(cfg["checks"]) == config.CHECKS
    ids = set()
    item = dict(id="test", argv=["echo", "ok"], finding_codes=[1, 255], timeout=0.5)
    config.validate_command(item, ids)
    assert ids == {"test"} and item["timeout"] == 0.5
    for invalid in [
        None,
        {},
        dict(id="bad id", argv=["echo"]),
        dict(id="black", argv=["echo"]),
        dict(id="test", argv=[]),
        dict(id="test", argv=[""]),
        dict(id="test", argv=[1]),
        dict(id="test", argv=["a\0b"]),
        dict(id="test", argv=["echo"], profile="unknown"),
    ]:
        with pytest.raises(ValueError):
            config.validate_command(invalid, set())
    for timeout in [True, 0, -1, float("inf"), float("nan"), "1"]:
        with pytest.raises(ValueError):
            config.validate_command(
                dict(id="test", argv=["echo"], timeout=timeout), set()
            )
    for codes in [None, [0], [256], [True], ["1"]]:
        with pytest.raises(ValueError):
            config.validate_command(
                dict(id="test", argv=["echo"], finding_codes=codes), set()
            )
    with pytest.raises(ValueError):
        config.validate_command(item, ids)


@pytest.mark.parametrize(
    "fragment",
    [
        "version=2",
        "version=1\nunknown=1",
        "version=1\nsource=[]",
        "version=1\nchecks=[]",
        'version=1\nsource=[""]',
        "version=1\nsource=[1]",
        'version=1\nsource="."',
        'version=1\nsource=["missing"]',
        'version=1\nchecks=["unknown"]',
        'version=1\nchecks=["black","black"]',
        "version=1\ncommands={}",
        "version=1\nrequired=[]",
        "version=1\n[required]\nunknown=[]",
        'version=1\n[required]\nfull="tests"',
        "version=1\n[required]\nfull=[1]",
        'version=1\n[required]\nfull=[""]',
        'version=1\nchecks=["mutator"]\n[[commands]]\nid="mutator"\nargv=["echo"]',
    ],
)
def test_invalid_configuration_is_rejected(tmp_path, fragment):
    """无效配置不能等到执行阶段才被忽略。

    Args:
        tmp_path: 配置目录。
        fragment: 完整的无效 TOML 文本。
    """
    p = tmp_path / "supervisor.toml"
    p.write_text(fragment)
    with pytest.raises(ValueError):
        config.load(tmp_path, p)


def test_advanced_settings_validation():
    """范围、类型和列表规则在配置边界校验。"""
    invalid = [
        [],
        {"unknown": {}},
        {"dryer": []},
        {"dryer": {"unknown": 1}},
        {"dryer": {"profile": "x"}},
        {"dryer": {"threshold": 1.1}},
        {"cpp-coverage": {"minimum": 101}},
    ]
    for value in [0, -1, True, float("inf"), float("nan"), "1"]:
        invalid.append({"dryer": {"threshold": value}})
    invalid += [
        {"dryer": {"min_lines": 1.5}},
        {"dryer": {"files": "a.py"}},
        {"dryer": {"files": [1]}},
        {"dryer": {"files": [""]}},
        {"dependencies": {"forbidden": {}}},
        {"dependencies": {"forbidden": [{"from": "a", "to": ""}]}},
        {"acceptance": {"limits": []}},
        {"acceptance": {"limits": {"time": float("inf")}}},
    ]
    for value in invalid:
        with pytest.raises(ValueError):
            adapters.validate_settings(value)
    adapters.validate_settings(
        {
            "dryer": {"threshold": 1, "min_lines": 1, "files": ["a.py"]},
            "cpp-coverage": {"minimum": 100},
            "acceptance": {"limits": {"time": 0}},
        }
    )
