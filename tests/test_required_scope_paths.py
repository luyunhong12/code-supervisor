"""必需检查、配置文件范围及真实编译目录的使用回归。"""

import copy
import json

import pytest

from code_supervisor import native
from code_supervisor.reporting import compare_reports
from test_native_usage import check_project
from test_tool_contracts import native_workspace
from test_usage_boundaries import report


@pytest.mark.parametrize("checker", ["cpp-docs", "cpp-build"])
@pytest.mark.parametrize("required", [False, True])
def test_required_inapplicable_check(tmp_path, monkeypatch, checker, required):
    """内置与高级检查都不能以不适用满足必需门禁，普通可选项仍允许跳过。

    Args:
        tmp_path: 独立工程与报告目录。
        monkeypatch: 命令行参数替换器。
        checker: 要求 C++ 源码的检查器。
        required: 是否将检查器设为必需项。
    """
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("x = 1\n")
    text = 'version=1\nsource=["main.py"]\nchecks=' + json.dumps([checker]) + "\n"
    if required:
        text += "[required]\nfull=" + json.dumps([checker]) + "\n"
    (root / "supervisor.toml").write_text(text)
    result, path = check_project(monkeypatch, root, tmp_path / "report")
    row = result["results"][0]
    assert result["exit_code"] == (2 if required else 0)
    assert row["status"] == ("error" if required else "not-applicable")
    sarif = json.loads(path.with_name("report.sarif").read_text())
    invocation = sarif["runs"][0]["invocations"][0]
    assert invocation["executionSuccessful"] is not required
    if required:
        assert "不适用" in row["reason"]
        assert invocation["toolExecutionNotifications"][0]["level"] == "error"


@pytest.mark.parametrize("change", ["delete", "move", "add", "fix"])
@pytest.mark.parametrize("kind", ["yaml", "xml"])
def test_configuration_scope_real_reports(tmp_path, monkeypatch, change, kind):
    """参数文件清单变化不能算修复，同一文件补注释仍可确认解决。

    Args:
        tmp_path: 工程与证据根目录。
        monkeypatch: CLI 参数替换器。
        change: 两次运行之间对配置的操作。
        kind: 参数配置格式。
    """
    root = tmp_path / "project"
    root.mkdir()
    configs = root / "config"
    configs.mkdir()
    (configs / "kept.yaml").write_text("# 长度参数\nlength: 2\n")
    old = configs / ("old." + kind)
    bad = "speed: 10\n" if kind == "yaml" else "<speed>10</speed>\n"
    good = (
        "# 速度参数\nspeed: 10\n"
        if kind == "yaml"
        else "<!-- 速度参数 -->\n<speed>10</speed>\n"
    )
    old.write_text(bad)
    (root / "supervisor.toml").write_text(
        'version=1\nsource=["."]\nchecks=["parameter-docs"]\n'
        '[settings.parameter-docs]\npaths=["config"]\n'
    )
    before, _ = check_project(monkeypatch, root, tmp_path / "before")
    assert before["exit_code"] == 1
    if change == "delete":
        old.unlink()
    elif change == "move":
        old.rename(configs / ("moved." + kind))
    else:
        old.write_text(good)
        if change == "add":
            (configs / "new.yaml").write_text("# 新参数\nnew: 1\n")
    after, _ = check_project(monkeypatch, root, tmp_path / "after")
    difference = compare_reports(before, after)
    assert difference["scope_changed"] == (change != "fix")
    expected = before["results"][0]["findings"]
    if change == "fix":
        assert difference["resolved"] == expected and difference["unverified"] == []
    else:
        assert difference["resolved"] == [] and difference["unverified"] == expected


@pytest.mark.parametrize("side", ["before", "after", "both"])
@pytest.mark.parametrize("missing", [None, {}, [1]])
def test_unknown_configuration_scope(side, missing):
    """旧报告缺清单或清单类型损坏时保守保留待验证诊断。

    Args:
        side: 缺少可靠清单的报告一方。
        missing: 缺失或无效的清单值。
    """
    before, after = report([1]), report([])
    for item in (before, after):
        item["results"][0].update(id="parameter-docs", configuration_files=[])
    targets = (
        (before, after) if side == "both" else [before if side == "before" else after]
    )
    for target in targets:
        if missing is None:
            target["results"][0].pop("configuration_files")
        else:
            target["results"][0]["configuration_files"] = missing
    result = compare_reports(before, after)
    assert result["scope_changed"] is True
    assert result["resolved"] == []
    assert result["unverified"] == before["results"][0]["findings"]


def test_configuration_scope_order_does_not_change_meaning():
    """配置文件清单顺序变化不会制造范围变更，也不改写输入报告。"""
    before, after = report([1]), report([])
    before["results"][0].update(
        id="parameter-docs", configuration_files=["a.xml", "b.yaml"]
    )
    after["results"][0].update(
        id="parameter-docs", configuration_files=["b.yaml", "a.xml"]
    )
    originals = copy.deepcopy((before, after))
    result = compare_reports(before, after)
    assert result["scope_changed"] is False
    assert result["resolved"] == before["results"][0]["findings"]
    assert (before, after) == originals


@pytest.mark.parametrize("case", ["clean", "analyzer", "tidy"])
def test_real_relative_include_directory(tmp_path, monkeypatch, case):
    """真实相对 -I 路径兼容包含记录、分析器和头文件专属 tidy 规则。

    Args:
        tmp_path: 独立项目及报告目录。
        monkeypatch: CLI 参数替换器。
        case: 无缺陷、分析器缺陷或 tidy 规则缺陷。
    """
    root = tmp_path / "project with [brackets]"
    root.mkdir()
    (root / "include").mkdir()
    source = {
        "clean": "inline double value(int a, int b){return double(a)/b;}\n",
        "analyzer": "inline double value(int, int){int number;return number;}\n",
        "tidy": "inline double value(int a, int b){return a/b;}\n",
    }[case]
    (root / "include/api.hh").write_text(source)
    (root / "main.cc").write_text(
        "#include <api.hh>\nint main(){return int(value(2,3));}\n"
    )
    (root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\nproject(Demo LANGUAGES CXX)\n"
        "add_executable(demo main.cc)\ntarget_compile_options(demo PRIVATE -I../include)\n"
    )
    (root / "supervisor.toml").write_text(
        'version=1\nsource=["main.cc","include/api.hh"]\nchecks=["clang-tidy"]\n'
        '[settings.clang-tidy]\nfiles=["include/api.hh"]\n'
        'inputs=["CMakeLists.txt","main.cc","include"]\n'
    )
    result, path = check_project(monkeypatch, root, tmp_path / "report")
    row = result["results"][0]
    assert result["exit_code"] == (0 if case == "clean" else 1)
    if case != "clean":
        assert row["findings"]
        assert {issue["file"] for issue in row["findings"]} == {"include/api.hh"}
        if case == "tidy":
            assert any(
                "bugprone-integer-division" in item["message"]
                for item in row["findings"]
            )
        sarif = json.loads(path.with_name("report.sarif").read_text())
        location = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
        assert location["artifactLocation"]["uri"] == "include/api.hh"


def test_compile_entries_keep_separate_directories(tmp_path, monkeypatch):
    """同一翻译单元的多个编译工作目录分别执行，不混用诊断路径基准。

    Args:
        tmp_path: 编译数据库和源码根目录。
        monkeypatch: 外部工具边界替换器。
    """
    build, _ = native_workspace(monkeypatch, tmp_path)
    (tmp_path / "main.cc").write_text("int main() {return 0;}\n")
    (tmp_path / "include").mkdir()
    (tmp_path / "include/api.hh").write_text("int value;\n")
    entries = []
    for name in ["build-a", "build-b"]:
        (tmp_path / name).mkdir()
        entries.append(
            dict(directory=name, file="../main.cc", command="g++ ../main.cc")
        )
    (build / "compile_commands.json").write_text(json.dumps(entries))
    calls = []

    def run(command, directory, output, label, *args, **kwargs):
        """验证每次仅使用自己的数据库条目，并输出相对路径诊断。

        Args:
            command: clang-tidy 参数列表。
            directory: 本条编译命令的工作目录。
            output: 检查证据目录。
            label: 日志名称。
            args: 超时位置参数。
            kwargs: 退出码约定。
        """
        from pathlib import Path

        calls.append(directory.name)
        database = Path(command[command.index("-p") + 1]) / "compile_commands.json"
        rows = json.loads(database.read_text())
        assert len(rows) == 1 and rows[0]["directory"] == str(directory)
        assert rows[0]["file"] == str(tmp_path / "main.cc")
        log = output / (label + ".log")
        log.write_text(
            ". ../include/api.hh\n../include/api.hh:3:4: warning: selected\n"
        )
        return log, 1

    monkeypatch.setattr(native, "run", run)
    result = native.clang_tidy(tmp_path, {"include/api.hh": "cpp"}, {}, tmp_path)
    assert calls == ["build-a", "build-b"]
    assert result["status"] == "fail" and len(result["findings"]) == 2
    assert {issue["file"] for issue in result["findings"]} == {"include/api.hh"}
    assert result["translation_units"] == ["main.cc"]
