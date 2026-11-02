"""验证真实 CLI 的报告、隔离、配置错误及检测失败语义。"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from code_supervisor.cpp import cpp_docs
from code_supervisor.process import execute

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args):
    """通过子进程运行真实入口，避免仅测试内部实现。"""
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    return subprocess.run(
        [sys.executable, "-m", "code_supervisor.cli", *map(str, args)],
        env=env,
        capture_output=True,
        text=True,
    )


def project(tmp_path, text='"""中文示例。"""\n', extra=""):
    """创建独立被测工程，返回根目录。"""
    (tmp_path / "sample.py").write_text(text)
    (tmp_path / "supervisor.toml").write_text(
        'version = 1\nsource = ["."]\nchecks = ["python-docs", "black", "ruff", "cpp-docs"]\n'
        + extra
    )
    return tmp_path


def report(root):
    """读取一次测试运行生成的唯一 JSON 报告。"""
    return json.loads(
        next((root / ".generated/supervisor").glob("*/report.json")).read_text()
    )


def test_good_project_and_no_source_changes(tmp_path):
    """有效工程通过，源码字节不变，C++ 明确不适用。"""
    root = project(tmp_path)
    before = (root / "sample.py").read_bytes()
    done = run_cli("check", root)
    assert done.returncode == 0, done.stderr + done.stdout
    result = report(root)
    assert result["source_unchanged"]
    assert (root / "sample.py").read_bytes() == before
    assert (
        next(r for r in result["results"] if r["id"] == "cpp-docs")["status"]
        == "not-applicable"
    )


def test_missing_docs_and_undefined_variable(tmp_path):
    """缺失说明及未定义变量均报告真实文件行号。"""
    root = project(tmp_path, "def value():\n    return missing_name\n")
    assert run_cli("check", root).returncode == 1
    issues = [f for r in report(root)["results"] for f in r.get("findings", [])]
    assert any(f["rule"] == "F821" and f["line"] == 2 for f in issues)
    assert any(f["rule"] == "PY-DOC" for f in issues)


def test_extensionless_untracked_entrypoint(tmp_path):
    """没有 Git 和后缀的 Python 入口也进入静态检查。"""
    root = project(tmp_path)
    (root / "entry").write_text(
        '#!/usr/bin/env python3\n"""中文入口。"""\nprint(unknown)\n'
    )
    assert run_cli("check", root).returncode == 1
    result = report(root)
    assert result["files"]["entry"] == "python"
    assert any(
        f["rule"] == "F821" for r in result["results"] for f in r.get("findings", [])
    )


@pytest.mark.parametrize("kind", ["empty", "escape", "unknown", "missing"])
def test_invalid_scope_never_passes(tmp_path, kind):
    """空扫描、越界和错误配置不能返回通过。"""
    root = project(tmp_path)
    if kind == "empty":
        (root / "sample.py").unlink()
    elif kind == "escape":
        (root / "supervisor.toml").write_text('version = 1\nsource = ["../"]\n')
    elif kind == "unknown":
        (root / "supervisor.toml").write_text('version = 1\nchecks = ["typo"]\n')
    else:
        (root / "supervisor.toml").unlink()
    assert run_cli("check", root).returncode == 2


def test_init_does_not_overwrite(tmp_path):
    """初始化拒绝覆盖项目已有配置。"""
    assert run_cli("init", tmp_path).returncode == 0
    original = (tmp_path / "supervisor.toml").read_bytes()
    assert run_cli("init", tmp_path).returncode == 2
    assert (tmp_path / "supervisor.toml").read_bytes() == original


def test_command_requires_explicit_execution(tmp_path):
    """默认不执行项目自定义命令，也不将其记作通过。"""
    extra = """[[commands]]
id = "tests"
argv = ["{python}", "-c", "open('executed', 'w').write('yes')"]
profile = "full"
"""
    root = project(tmp_path, extra=extra)
    assert run_cli("check", root, "--profile", "full").returncode == 2
    assert not (root / "executed").exists()


def test_missing_tool_is_error(tmp_path):
    """命令不存在时报告错误，不把失败当作干净结果。"""
    result = execute(
        ["/definitely/nonexistent/supervisor-tool"], tmp_path, tmp_path / "log"
    )
    assert result["status"] == "error"


@pytest.mark.parametrize("code,status", [(0, "pass"), (1, "fail"), (2, "error")])
def test_exit_status_mapping(tmp_path, code, status):
    """区分检查通过、发现问题和执行错误。"""
    result = execute(
        [sys.executable, "-c", f"raise SystemExit({code})"], tmp_path, tmp_path / "log"
    )
    assert result["status"] == status


def test_timeout_terminates_child_group(tmp_path):
    """超时回收子进程，延迟写入不能发生。"""
    marker = tmp_path / "late"
    child = "import time,pathlib; time.sleep(1); pathlib.Path('late').write_text('bad')"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)"
    result = execute(
        [sys.executable, "-c", parent], tmp_path, tmp_path / "log", timeout=0.2
    )
    assert result["status"] == "error"
    import time

    time.sleep(1.1)
    assert not marker.exists()


def test_source_changed_invalidates_evidence(tmp_path):
    """配置命令修改源码时，报告不宣称一致快照。"""
    extra = """[[commands]]
id = "tests"
argv = ["{python}", "-c", "open('sample.py', 'a').write('x = 1')"]
profile = "full"
"""
    root = project(tmp_path, extra=extra)
    assert run_cli("check", root, "--profile", "full", "--run-commands").returncode == 2
    assert report(root)["source_unchanged"] is False


def test_unconfigured_required_gate_is_incomplete(tmp_path):
    """完整模式要求的测试缺失时不能通过。"""
    root = project(tmp_path, extra='[required]\nfull = ["tests"]\n')
    assert run_cli("check", root, "--profile", "full").returncode == 2
    assert any(
        r["id"] == "tests" and r["status"] == "not-run" for r in report(root)["results"]
    )


def test_cpp_detects_missing_function_docs(tmp_path):
    """有文件注释但缺函数说明时仍然失败。"""
    (tmp_path / "part.hh").write_text(
        "/** @file part.hh\n * @brief 中文文件。\n */\nint Add(int x) { return x + 1; }\n"
    )
    result = cpp_docs(tmp_path, ["part.hh"])
    assert result["status"] == "fail"
    assert any(f["rule"] == "CPP-DOC" for f in result["findings"])


def test_cpp_documented_constructor_and_template(tmp_path):
    """模板、类和构造函数前的 Doxygen 说明可以被识别。"""
    (tmp_path / "part.hh").write_text(
        """/** @file part.hh
 * @brief 中文文件。
 */
/** @brief 数值容器。 */
template<class T> class Box {
 public:
  /** @brief 初始化。 */
  Box() {}
};
"""
    )
    result = cpp_docs(tmp_path, ["part.hh"])
    assert result["status"] == "pass", result
    assert result["definitions"] == 2


def test_cpp_parse_failure_is_error(tmp_path):
    """不完整 C++ 语法不会被当作通过。"""
    (tmp_path / "broken.cc").write_text("class Broken { void f( ;")
    assert cpp_docs(tmp_path, ["broken.cc"])["status"] == "error"


def test_generated_and_symlink_files_are_excluded(tmp_path):
    """生成物与符号链接不进入检查，普通未跟踪源码仍进入。"""
    root = project(tmp_path)
    generated = root / "build"
    generated.mkdir()
    (generated / "bad.py").write_text("not valid python !")
    (root / "link.py").symlink_to(generated / "bad.py")
    assert run_cli("check", root).returncode == 0
    assert list(report(root)["files"]) == ["sample.py"]


def test_project_black_configuration_is_honored(tmp_path):
    """已有 Black 字符串规范选项被保留，检查不会擅自换排版。"""
    root = project(tmp_path, '"""中文示例。"""\n\nx = \'text\'\n')
    (root / "pyproject.toml").write_text(
        "[tool.black]\nskip-string-normalization = true\n"
    )
    assert run_cli("check", root).returncode == 0
