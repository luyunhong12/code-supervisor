"""真实 C++ 工具链的执行授权、选定范围与报告可移植性回归。"""

import json
import shlex
import sys

import pytest

from code_supervisor import cli, native
from code_supervisor.reporting import compare_reports
from code_supervisor.tasks import CheckError, tool
from test_tool_contracts import install_runner, native_workspace


def check_project(monkeypatch, root, output, enabled=True):
    """从 CLI 入口执行完整检查并读取落盘报告。

    Args:
        monkeypatch: 命令行参数替换器。
        root: 待检查工程。
        output: 独立报告目录。
        enabled: 是否显式授权执行配置程序。
    """
    argv = [
        "supervisor",
        "check",
        str(root),
        "--profile",
        "full",
        "--output",
        str(output),
    ]
    if enabled:
        argv.append("--run-commands")
    monkeypatch.setattr(sys, "argv", argv)
    code = cli.main()
    report_path = next(output.glob("*/report.json"))
    report = json.loads(report_path.read_text())
    assert code == report["exit_code"]
    assert report["source_unchanged"] is True
    return report, report_path


@pytest.mark.parametrize(
    "custom,enabled", [(False, False), (True, False), (True, True)]
)
def test_doxygen_execution_authorization(tmp_path, monkeypatch, custom, enabled):
    """默认检测器可直接运行，自定义程序只有明确授权后才实际执行。

    Args:
        tmp_path: 独立项目与报告目录。
        monkeypatch: 命令行参数替换器。
        custom: 是否配置自定义 Doxygen 程序。
        enabled: 是否开启执行授权。
    """
    root = tmp_path / "project"
    root.mkdir()
    (root / "api.hh").write_text("/** @file api.hh\n * @brief 接口文件。\n */\n")
    marker = tmp_path / "executed"
    wrapper = tmp_path / "doxygen-wrapper"
    wrapper.write_text(
        "#!/bin/sh\n"
        + "printf executed > "
        + shlex.quote(str(marker))
        + "\n"
        + "exec "
        + shlex.quote(tool("doxygen"))
        + ' "$@"\n'
    )
    wrapper.chmod(0o755)
    configuration = 'version=1\nsource=["api.hh"]\nchecks=["doxygen"]\n'
    if custom:
        configuration += (
            "[settings.doxygen]\nexecutable=" + json.dumps(str(wrapper)) + "\n"
        )
    (root / "supervisor.toml").write_text(configuration)
    report, _ = check_project(monkeypatch, root, tmp_path / "report", enabled)
    expected = "not-run" if custom and not enabled else "pass"
    assert report["results"][0]["status"] == expected
    assert marker.exists() == (custom and enabled)
    if expected == "not-run":
        assert "--run-commands" in report["results"][0]["reason"]


@pytest.fixture
def cpp_project(tmp_path):
    """建立含第三方构建依赖和未选源文件的真实 CMake 工程。

    Args:
        tmp_path: 测试隔离根目录。
    """
    root = tmp_path / "project"
    root.mkdir()
    (root / "vendor").mkdir()
    (root / "api.hh").write_text("inline int value() { return 0; }\n")
    (root / "main.cc").write_text('#include "api.hh"\nint main(){return value();}\n')
    (root / "other.cc").write_text(
        "int other(){ int uninitialized; return uninitialized; }\n"
    )
    (root / "vendor/legacy.cc").write_text(
        "int legacy(){ int uninitialized; return uninitialized; }\n"
    )
    (root / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\nproject(Demo LANGUAGES CXX)\n"
        "add_executable(demo main.cc)\n"
        "add_library(other STATIC other.cc)\n"
        "add_library(legacy STATIC vendor/legacy.cc)\n"
    )
    return root


def configure_cpp(root, names):
    """配置宽构建输入和明确的窄诊断范围。

    Args:
        root: 真实 CMake 工程目录。
        names: clang-tidy 选定的文件列表。
    """
    (root / "supervisor.toml").write_text(
        'version=1\nsource=["main.cc","other.cc","api.hh"]\n'
        'exclude=["vendor/**"]\nchecks=["clang-tidy"]\n'
        "[settings.clang-tidy]\nfiles=" + json.dumps(names) + "\n"
        'inputs=["CMakeLists.txt","main.cc","other.cc","api.hh","vendor"]\n'
    )


def test_real_clang_scope_and_stable_reports(cpp_project, tmp_path, monkeypatch):
    """真实构建保留依赖，排除其诊断；未改源码的报告差异为空且 SARIF 可定位。

    Args:
        cpp_project: 带范围外缺陷的工程。
        tmp_path: 本次证据根目录。
        monkeypatch: CLI 参数替换器。
    """
    configure_cpp(cpp_project, ["main.cc"])
    report, _ = check_project(monkeypatch, cpp_project, tmp_path / "clean")
    row = report["results"][0]
    assert report["exit_code"] == 0 and row["findings"] == []
    assert row["translation_units"] == ["main.cc"]
    (cpp_project / "main.cc").write_text("int main(){ int value; return value; }\n")
    before, path = check_project(monkeypatch, cpp_project, tmp_path / "first")
    after, _ = check_project(monkeypatch, cpp_project, tmp_path / "second")
    assert before["exit_code"] == after["exit_code"] == 1
    assert before["results"][0]["findings"][0]["file"] == "main.cc"
    difference = compare_reports(before, after)
    assert (
        difference["added"] == difference["resolved"] == difference["unverified"] == []
    )
    assert difference["scope_changed"] is False
    sarif = json.loads(path.with_name("report.sarif").read_text())
    location = sarif["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert location["artifactLocation"]["uri"] == "main.cc"


@pytest.mark.parametrize("included", [True, False])
def test_real_header_selection(cpp_project, tmp_path, monkeypatch, included):
    """只选头文件仍捕获真实缺陷，未被编译单元包含时不能假通过。

    Args:
        cpp_project: 带真实编译数据库的工程。
        tmp_path: 报告根目录。
        monkeypatch: CLI 参数替换器。
        included: 主文件是否实际包含待查头文件。
    """
    configure_cpp(cpp_project, ["api.hh"])
    (cpp_project / "api.hh").write_text(
        "inline int value(){ int number; return number; }\n"
    )
    if not included:
        (cpp_project / "main.cc").write_text("int main(){ return 0; }\n")
    report, _ = check_project(monkeypatch, cpp_project, tmp_path / "report")
    row = report["results"][0]
    if included:
        assert report["exit_code"] == 1
        assert row["findings"]
        assert {issue["file"] for issue in row["findings"]} == {"api.hh"}
    else:
        assert report["exit_code"] == 2
        assert "未被本轮翻译单元包含" in row["reason"]


@pytest.mark.parametrize("missing", ["input", "unit", "all_units"])
def test_clang_missing_evidence(tmp_path, monkeypatch, missing):
    """选定文件未复制、未编译或没有可分析单元均保留为执行错误。

    Args:
        tmp_path: 独立工作目录。
        monkeypatch: 构建边界替换器。
        missing: 缺失的证据类型。
    """
    build, _ = native_workspace(monkeypatch, tmp_path)
    name = "api.hh" if missing == "all_units" else "a.cc"
    if missing != "input":
        (tmp_path / name).write_text("// 源码\n")
    (build / "compile_commands.json").write_text("[]")
    with pytest.raises(CheckError, match="inputs|编译数据库不含"):
        native.clang_tidy(tmp_path, {name: "cpp"}, {}, tmp_path)


@pytest.mark.parametrize("absolute", [False, True])
def test_clang_filters_diagnostics_without_hiding_protocol_errors(
    tmp_path, monkeypatch, absolute
):
    """绝对与相对路径均稳定，范围外诊断可过滤，编译错误不随范围过滤。

    Args:
        tmp_path: 模拟工具工作目录。
        monkeypatch: 工具边界替换器。
        absolute: 工具是否返回绝对路径。
    """
    build, _ = native_workspace(monkeypatch, tmp_path)
    (tmp_path / "a.cc").write_text("int a;\n")
    (build / "compile_commands.json").write_text(json.dumps([dict(file="a.cc")]))
    prefix = str(tmp_path) + "/" if absolute else ""
    text = prefix + "unselected.hh:2:3: warning: ignored\n"
    calls = install_runner(monkeypatch, native, tmp_path, {"tool.log": text}, 1)
    result = native.clang_tidy(tmp_path, {"a.cc": "cpp"}, {}, tmp_path)
    assert result["status"] == "pass" and result["findings"] == []
    assert calls[0][0][0][1] == str(tmp_path / "a.cc")
    install_runner(
        monkeypatch,
        native,
        tmp_path,
        {"tool.log": text + prefix + "a.cc:7:2: warning: kept\n"},
        1,
    )
    second = tmp_path / "second"
    second.mkdir()
    result = native.clang_tidy(tmp_path, {"a.cc": "cpp"}, {}, second)
    assert result["findings"] == [
        dict(file="a.cc", line=7, rule="CLANG-TIDY", message="kept")
    ]
    install_runner(
        monkeypatch,
        native,
        tmp_path,
        {"tool.log": "unselected.hh:2:3: error: bad [clang-diagnostic-error]\n"},
        1,
    )
    third = tmp_path / "third"
    third.mkdir()
    with pytest.raises(CheckError, match="无法解析"):
        native.clang_tidy(tmp_path, {"a.cc": "cpp"}, {}, third)
