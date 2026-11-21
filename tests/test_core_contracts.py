"""文件隔离、进程边界和基础文档检查的行为契约。"""

import hashlib
import json
import os
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

from code_supervisor import tasks, process, checks, config, cpp
from code_supervisor.tasks import CheckError


def test_snapshot_manifest_and_protection(tmp_path):
    """副本保持字节与执行权限，排除生成物并拒绝无效输入。

    Args:
        tmp_path: 独立输入输出目录。
    """
    root = tmp_path / "source"
    root.mkdir()
    (root / "nested").mkdir()
    (root / "nested/a.py").write_bytes(b"print(1)\n")
    (root / "nested/a.py").chmod(0o755)
    (root / "build").mkdir()
    (root / "build/old").write_text("old")
    out = tmp_path / "out"
    out.mkdir()
    work = tasks.snapshot(root, out, dict(inputs=["nested", "build"]))
    assert (work / "nested/a.py").read_bytes() == b"print(1)\n"
    assert os.access(work / "nested/a.py", os.X_OK)
    assert not (work / "build/old").exists()
    assert json.loads((out / "snapshot.json").read_text()) == {
        "nested/a.py": hashlib.sha256(b"print(1)\n").hexdigest()
    }
    for index, inputs in enumerate([[], None, ["missing"], ["build"]]):
        folder = tmp_path / f"bad{index}"
        folder.mkdir()
        with pytest.raises(CheckError):
            tasks.snapshot(root, folder, dict(inputs=inputs))
    (root / "nested/link").symlink_to(root / "nested/a.py")
    folder = tmp_path / "links"
    folder.mkdir()
    with pytest.raises(CheckError, match="符号链接"):
        tasks.snapshot(root, folder, dict(inputs=["nested"]))
    nested_out = root / "out"
    nested_out.mkdir()
    with pytest.raises(CheckError, match="无效副本"):
        tasks.snapshot(root, nested_out, dict(inputs=["."]))


def test_argv_and_selected_files(tmp_path):
    """只展开完整占位符，选定文件须属于范围并且语言匹配。

    Args:
        tmp_path: 根目录占位。
    """
    assert tasks.argv(
        {"command": ["{python}", "{work}", "prefix{work}"]},
        "command",
        {"{work}": "/work"},
    ) == [sys.executable, "/work", "prefix{work}"]
    for value in [None, [], [""], [1], "echo"]:
        with pytest.raises(CheckError):
            tasks.argv({"command": value}, "command")
    files = {"a.py": "python", "b.cc": "cpp"}
    assert tasks.selected_files(tmp_path, files, {}, "python") == ["a.py"]
    for value in [[], ["b.cc"], ["missing"], [1], "a.py"]:
        with pytest.raises(CheckError):
            tasks.selected_files(tmp_path, files, {"files": value}, "python")


def test_tool_priority_and_missing(tmp_path, monkeypatch):
    """同环境、PATH、Node 和独立目录按明确顺序解析工具。

    Args:
        tmp_path: 模拟工具安装目录。
        monkeypatch: 替换解释器和环境。
    """
    root = tmp_path / "install"
    (root / "src/code_supervisor").mkdir(parents=True)
    monkeypatch.setattr(tasks, "__file__", str(root / "src/code_supervisor/tasks.py"))
    executable = root / "venv/bin/python"
    executable.parent.mkdir(parents=True)
    monkeypatch.setattr(tasks, "sys", SimpleNamespace(executable=str(executable)))
    local = executable.parent / "probe"
    local.write_text("")
    monkeypatch.setenv("PATH", "")
    assert tasks.tool("probe") == str(local)
    local.unlink()
    search = root / "path"
    search.mkdir()
    binary = search / "probe"
    binary.write_text("")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(search))
    assert tasks.tool("probe") == str(binary)
    binary.unlink()
    node = root / ".tools/node_modules/.bin/probe"
    node.parent.mkdir(parents=True)
    node.write_text("")
    assert tasks.tool("probe") == str(node)
    node.unlink()
    bundled = root / ".tools/probe"
    bundled.write_text("")
    assert tasks.tool("probe") == str(bundled)
    bundled.unlink()
    with pytest.raises(CheckError, match="probe"):
        tasks.tool("probe")


@pytest.mark.parametrize(
    "result,accepted,expected",
    [
        (dict(status="pass", returncode=0), (0,), 0),
        (dict(status="fail", returncode=1), (0, 1), 1),
        (dict(status="error", reason="超时"), (0,), None),
    ],
)
def test_run_boundary(tmp_path, monkeypatch, result, accepted, expected):
    """外部执行错误不能因缺失退出码而变成检查成功。

    Args:
        tmp_path: 日志目录。
        monkeypatch: 执行边界替换器。
        result: 模拟执行结果。
        accepted: 明确接受的退出码集合。
        expected: 成功退出码，None 表示应报错。
    """

    def execute(*args, **kwargs):
        """返回模拟执行结果。

        Args:
            args: 命令、工作目录、日志和超时参数。
            kwargs: 分类选项。
        """
        assert args == (["tool"], tmp_path, tmp_path / "label.log", 5)
        assert kwargs == {"finding_codes": ()}
        return result

    monkeypatch.setattr(tasks, "execute", execute)
    if expected is None:
        with pytest.raises(CheckError, match="超时"):
            tasks.run(["tool"], tmp_path, tmp_path, "label", 5, accepted)
    else:
        assert tasks.run(["tool"], tmp_path, tmp_path, "label", 5, accepted) == (
            tmp_path / "label.log",
            expected,
        )


@pytest.mark.parametrize("event", ["timeout", "interrupt"])
def test_process_terminates_and_reaps(tmp_path, monkeypatch, event):
    """超时与中断回收独立进程组，中断必须向调用者传播。

    Args:
        tmp_path: 日志目录。
        monkeypatch: 进程和时钟替换器。
        event: 模拟中断类型。
    """
    waited = []
    killed = []

    def wait(timeout=None):
        """第一次等待抛异常，回收等待正常返回。

        Args:
            timeout: 首次等待的秒数，回收时省略。
        """
        waited.append(timeout)
        if timeout is not None:
            if event == "interrupt":
                raise KeyboardInterrupt()
            raise subprocess.TimeoutExpired(["tool"], timeout)
        return -9

    def popen(argv, **kwargs):
        """核对独立进程组与环境。

        Args:
            argv: 展开后的程序参数。
            kwargs: 进程配置。
        """
        assert argv == [sys.executable, "-V"]
        assert kwargs["start_new_session"] is True
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        assert kwargs["stderr"] == subprocess.STDOUT and kwargs["cwd"] == tmp_path
        return SimpleNamespace(pid=123, wait=wait)

    def kill(pid, sig):
        """记录信号并模拟进程已经退出。

        Args:
            pid: 目标进程组。
            sig: 终止信号。
        """
        killed.append((pid, sig))
        raise ProcessLookupError()

    monkeypatch.setattr(process.subprocess, "Popen", popen)
    monkeypatch.setattr(process.os, "killpg", kill)
    if event == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            process.execute(["{python}", "-V"], tmp_path, tmp_path / "log", timeout=3)
    else:
        result = process.execute(
            ["{python}", "-V"], tmp_path, tmp_path / "log", timeout=3
        )
        assert result["status"] == "error" and "超过 3 秒" in result["reason"]
    assert waited == [3, None] and killed == [(123, signal.SIGKILL)]


@pytest.mark.parametrize(
    "source,rules",
    [
        ("", []),
        ('"""English."""', ["PY-CN"]),
        ('"中文。"', ["PY-QUOTE"]),
        ('"""中文 @param x。"""', ["PY-GOOGLE"]),
        ("def f(", ["PY-SYNTAX"]),
        ('"""模块。"""\nclass A:\n pass\n', ["PY-DOC"]),
    ],
)
def test_python_documentation_rules(tmp_path, source, rules):
    """文档语法、语言和形式分别产生可定位的诊断。

    Args:
        tmp_path: 源码目录。
        source: 被检查源码。
        rules: 预期规则标识。
    """
    (tmp_path / "a.py").write_text(source)
    result = checks.python_docs(tmp_path, ["a.py"])
    assert [x["rule"] for x in result["findings"]] == rules
    assert result["status"] == ("fail" if rules else "pass")
    if rules:
        assert result["findings"][0]["line"] >= 1


def test_black_failures_and_trailing_comma(tmp_path):
    """无法支持的配置报错；无效源码与排版不一致各自给出诊断。

    Args:
        tmp_path: 源码和配置目录。
    """
    p = tmp_path / "pyproject.toml"
    p.write_text("[tool.black]\nunknown=true")
    assert checks.black_check(tmp_path, ["a.py"])["status"] == "error"
    p.write_text(
        '[tool.black]\ntarget-version=["py311"]\nskip-magic-trailing-comma=true\n'
    )
    (tmp_path / "a.py").write_text("x = [1, 2]\n")
    assert checks.black_check(tmp_path, ["a.py"])["status"] == "pass"
    (tmp_path / "a.py").write_text("x=[1,2,]\n")
    assert (
        checks.black_check(tmp_path, ["a.py"])["findings"][0]["rule"] == "BLACK-FORMAT"
    )
    (tmp_path / "a.py").write_text("def f(")
    assert (
        checks.black_check(tmp_path, ["a.py"])["findings"][0]["rule"] == "BLACK-PARSE"
    )


def test_discover_scope_and_scripts(tmp_path):
    """扫描识别显式文件与脚本，排除匹配模式、生成目录和目录链接。

    Args:
        tmp_path: 独立工程目录。
    """
    for name, text in [
        ("a.py", ""),
        ("b.cc", ""),
        ("script", "#!/usr/bin/python3\n"),
        ("plain", "python text"),
        ("shell", "#!/bin/bash\n"),
        ("ignore.py", ""),
    ]:
        (tmp_path / name).write_text(text)
    (tmp_path / "build").mkdir()
    (tmp_path / "build/a.py").write_text("")
    (tmp_path / "link").symlink_to(tmp_path / "build", target_is_directory=True)
    assert config.discover(tmp_path, dict(source=["."], exclude=["ignore.py"])) == {
        "a.py": "python",
        "b.cc": "cpp",
        "script": "python",
    }
    assert config.discover(tmp_path, dict(source=["a.py"], exclude=[])) == {
        "a.py": "python"
    }


def test_cpp_comment_order_and_unknowns(tmp_path):
    """多行文档保持顺序，普通注释不能冒充 Doxygen，局部声明不变成接口。

    Args:
        tmp_path: C++ 源码目录。
    """
    from tree_sitter import Language, Parser
    import tree_sitter_cpp

    source = b"/// first\n/// second\nint f(int a);\n"
    tree = Parser(Language(tree_sitter_cpp.language())).parse(source)
    node = list(cpp.targets(tree))[0]
    assert cpp.preceding(node, source) == "/// first\n/// second"
    src = "/** @file a.hh\n * @brief 文件。\n */\n// 普通说明\nint f();\n/** 说明但没有brief。 */\nint g();\n"
    (tmp_path / "a.hh").write_text(src)
    result = cpp.cpp_docs(tmp_path, ["a.hh"])
    assert [x["rule"] for x in result["findings"]] == ["CPP-DOC", "CPP-BRIEF"]
    source = b"class Forward;\nint f(){ int local(int); return 0; }"
    tree = Parser(Language(tree_sitter_cpp.language())).parse(source)
    assert len(list(cpp.targets(tree))) == 1


def test_cpp_masks_multiple_registrations_without_shifting():
    """多个注册调用和字符串中的假宏不互相影响。"""
    source = b'GZ_ADD_PLUGIN(A,B)\nGZ_ADD_PLUGIN_ALIAS(A,"name")\nint f(int x){ return x; }\n'
    masked = cpp.cpp_parameter_source(source)
    assert (
        masked
        == b'GZ_ADD_PLUGIN(A,B);\nGZ_ADD_PLUGIN_ALIAS(A,"name");\nint f(int x){ return x; }\n'
    )
    source = b"/*\nsignals:\n*/\nclass A {\nsignals:\n void f();\n};"
    masked = cpp.qt_parameter_source(source)
    assert masked == source.replace(b"\nclass A {\nsignals:", b"\nclass A {\npublic :")
