"""C++ 构建和检测器的失败协议及隔离变异边界。"""

import json

import pytest

from code_supervisor import native
from code_supervisor.tasks import CheckError
from test_tool_contracts import install_runner, native_workspace


@pytest.mark.parametrize(
    "flags,marker,expected",
    [
        ("", False, "pass"),
        ("--coverage -O0", True, "pass"),
        ("--coverage -O0", False, "error"),
    ],
)
def test_prepare_verifies_real_compile_flags(
    tmp_path, monkeypatch, flags, marker, expected
):
    """插桩开关必须出现在自有文件的真实编译命令中。

    Args:
        tmp_path: 独立构建根目录。
        monkeypatch: 进程与副本边界替换器。
        flags: 请求的插桩选项。
        marker: 编译数据库是否保留插桩选项。
        expected: 预期状态。
    """

    def snapshot(*args):
        """返回准备好的独立目录。

        Args:
            args: 快照边界参数。
        """
        return tmp_path

    monkeypatch.setattr(native, "snapshot", snapshot)
    commands = [
        dict(
            file=str(tmp_path / "a.cc"),
            command="g++ " + ("--coverage" if marker else ""),
        )
    ]
    calls = install_runner(
        monkeypatch, native, tmp_path, {".build/compile_commands.json": commands}
    )
    if expected == "error":
        with pytest.raises(CheckError, match="插桩"):
            native.prepare(tmp_path, {}, tmp_path, flags)
    else:
        work, build = native.prepare(
            tmp_path, dict(jobs=3, configure_args=["-DEXTRA=ON"]), tmp_path, flags
        )
        assert work == tmp_path and build == tmp_path / ".build"
        assert calls[0][0][0][-1] == "-DEXTRA=ON"
        assert calls[1][0][0][-2:] == ["--parallel", "3"]
        if flags:
            assert "-DCMAKE_CXX_FLAGS=" + flags in calls[0][0][0]
    with pytest.raises(CheckError, match="越界"):
        native.prepare(tmp_path, dict(cmake_source=".."), tmp_path)


@pytest.mark.parametrize("code,expected", [(0, "pass"), (8, "fail")])
def test_cpp_build_reports_test_result(tmp_path, monkeypatch, code, expected):
    """构建完成后仍按实际测试退出码判定。

    Args:
        tmp_path: 测试输出目录。
        monkeypatch: 工具替换器。
        code: CTest 退出码。
        expected: 预期检查状态。
    """
    native_workspace(monkeypatch, tmp_path)
    install_runner(
        monkeypatch,
        native,
        tmp_path,
        {
            "ctest.xml": "<testsuite><testcase>"
            + ("<failure/>" if code else "")
            + "</testcase></testsuite>"
        },
        code,
    )
    result = native.cpp_build(tmp_path, {}, {}, tmp_path)
    assert result["status"] == expected and result["tests"] == 1


@pytest.mark.parametrize(
    "text,code,expected",
    [
        ("", 0, "pass"),
        ("a.cc:3:4: warning: bad usage\n", 1, "fail"),
        ("", 1, "error"),
        ("clang-diagnostic-error", 1, "error"),
    ],
)
def test_clang_tidy_protocol(tmp_path, monkeypatch, text, code, expected):
    """编译错误及无可解析诊断的失败不能变成普通候选。

    Args:
        tmp_path: 构建目录。
        monkeypatch: 工具替换器。
        text: 工具诊断文本。
        code: 工具退出码。
        expected: 预期状态。
    """
    build, _ = native_workspace(monkeypatch, tmp_path)
    (tmp_path / "a.cc").write_text("int main() { return 0; }\n")
    (build / "compile_commands.json").write_text(
        json.dumps(
            [dict(file=str(tmp_path / "a.cc")), dict(file="/outside/not-own.cc")]
        )
    )
    install_runner(monkeypatch, native, tmp_path, {"tool.log": text}, code)
    if expected == "error":
        with pytest.raises(CheckError):
            native.clang_tidy(tmp_path, {"a.cc": "cpp"}, {}, tmp_path)
    else:
        result = native.clang_tidy(tmp_path, {"a.cc": "cpp"}, {}, tmp_path)
        assert result["status"] == expected and result["translation_units"] == ["a.cc"]
        if expected == "fail":
            assert result["findings"] == [
                dict(file="a.cc", line=3, rule="CLANG-TIDY", message="bad usage")
            ]
    (build / "compile_commands.json").write_text("[]")
    with pytest.raises(CheckError, match="不含"):
        native.clang_tidy(tmp_path, {"a.cc": "cpp"}, {}, tmp_path)


def test_clang_failure_after_previous_warning(tmp_path, monkeypatch):
    """前一翻译单元的警告不能掩盖后一单元执行失败。

    Args:
        tmp_path: 模拟编译数据库目录。
        monkeypatch: 替换运行边界。
    """
    build, _ = native_workspace(monkeypatch, tmp_path)
    (tmp_path / "a.cc").write_text("int main() { return 0; }\n")
    (build / "compile_commands.json").write_text(
        json.dumps([dict(file=str(tmp_path / name)) for name in ["a.cc", "b.cc"]])
    )

    (tmp_path / "b.cc").write_text("int b() { return 0; }\n")

    def run(command, work, output, label, *args, **kwargs):
        """模拟首项正常诊断与第二项无诊断失败。

        Args:
            command: 工具参数。
            work: 副本目录。
            output: 证据目录。
            label: 日志前缀。
            args: 超时等附加位置参数。
            kwargs: 退出码配置。
        """
        log = output / (label + ".log")
        log.write_text("a.cc:1:1: warning: first\n" if label == "tidy-0" else "")
        return log, 1

    install_runner(monkeypatch, native, tmp_path, {})
    monkeypatch.setattr(native, "run", run)
    with pytest.raises(CheckError, match="无可解析诊断"):
        native.clang_tidy(tmp_path, {"a.cc": "cpp", "b.cc": "cpp"}, {}, tmp_path)


def test_clang_relative_database_path(tmp_path, monkeypatch):
    """编译数据库的相对 file 按该项 directory 解析。

    Args:
        tmp_path: 工程目录。
        monkeypatch: 工具替换器。
    """
    build, _ = native_workspace(monkeypatch, tmp_path)
    (tmp_path / "a.cc").write_text("int main() { return 0; }\n")
    (build / "compile_commands.json").write_text(
        json.dumps([dict(directory=str(tmp_path), file="a.cc")])
    )
    install_runner(monkeypatch, native, tmp_path, {"tool.log": ""})
    assert native.clang_tidy(tmp_path, {"a.cc": "cpp"}, {}, tmp_path)[
        "translation_units"
    ] == ["a.cc"]


@pytest.mark.parametrize("threshold,expected", [(1, "fail"), (2, "pass")])
def test_complexity_threshold(tmp_path, threshold, expected):
    """圈复杂度达到门槛时报告，空函数集合不能通过。

    Args:
        tmp_path: 源码目录。
        threshold: 复杂度门槛。
        expected: 预期状态。
    """
    (tmp_path / "a.cc").write_text("int f(){ return 1; }")
    result = native.cpp_complexity(
        tmp_path, {"a.cc": "cpp"}, dict(threshold=threshold), tmp_path
    )
    assert result["status"] == expected
    if expected == "fail":
        assert result["findings"][0]["line"] == 1
    (tmp_path / "a.cc").write_text("int value;")
    with pytest.raises(CheckError):
        native.cpp_complexity(tmp_path, {"a.cc": "cpp"}, {}, tmp_path)


@pytest.mark.parametrize(
    "compile_code,test_code,budget,error,expected",
    [
        (0, 8, 10, False, "pass"),
        (0, 0, 10, False, "fail"),
        (1, 0, 10, False, "error"),
        (2, 0, 10, False, "error"),
        (0, 8, 1, False, "error"),
        (0, 8, 10, True, "error"),
    ],
)
def test_cpp_mutation_classification_and_restore(
    tmp_path, monkeypatch, compile_code, test_code, budget, error, expected
):
    """编译无效、存活、预算耗尽和执行错误分别分类，源文件始终恢复。

    Args:
        tmp_path: 隔离源码目录。
        monkeypatch: 工具边界替换器。
        compile_code: 变异构建退出码。
        test_code: 变异测试退出码。
        budget: 允许执行的变异数。
        error: 是否模拟测试基础设施错误。
        expected: 预期检查状态。
    """
    original = b"int f(int x){ return x + 1 + 2; }"
    (tmp_path / "a.cc").write_bytes(original)
    native_workspace(monkeypatch, tmp_path)
    install_runner(monkeypatch, native, tmp_path, {}, compile_code)

    def test(work, build, options, output, label, accept_failure=False):
        """基线通过，变异阶段返回指定状态。

        Args:
            work: 副本目录。
            build: 构建目录。
            options: 检查配置。
            output: 证据目录。
            label: 当前执行阶段。
            accept_failure: 是否允许测试失败退出码。
        """
        if label == "baseline":
            return 0, output / "base.log", 1
        assert accept_failure is True
        if error:
            raise CheckError("运行库不可用")
        assert (work / "a.cc").read_bytes() != original
        return test_code, output / "test.log", 1

    monkeypatch.setattr(native, "test_project", test)
    result = native.cpp_mutation(
        tmp_path, {"a.cc": "cpp"}, dict(max_mutants=budget), tmp_path
    )
    assert result["status"] == expected
    assert (tmp_path / "a.cc").read_bytes() == original
    rows = json.loads((tmp_path / "cpp-mutation.json").read_text())
    expected_outcome = (
        "error"
        if error
        else "invalid" if compile_code else "survived" if test_code == 0 else "killed"
    )
    assert rows[0]["outcome"] == expected_outcome
    if budget == 1:
        assert rows[1]["outcome"] == "budget-exhausted"
    if expected == "pass":
        assert result["executed"] == 2


def test_cpp_mutation_sites_ignore_globals_and_literals():
    """只变异函数体真实运算符，位置使用字节偏移和一基行号。"""
    source = b'int global=1+2;\nint f(int a){ const char *s="+"; return a+1; }'
    rows = native.mutation_sites(source)
    assert len(rows) == 1
    assert rows[0]["line"] == 2 and source[rows[0]["start"] : rows[0]["end"]] == b"+"
    assert rows[0]["replacement"] == "-"
    with pytest.raises(CheckError):
        native.mutation_sites(b"int f( ;")
