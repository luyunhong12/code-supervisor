"""真实工具集成测试：用已知错误验证检出能力与证据分类。"""

import json
from pathlib import Path
import sys

import pytest

from code_supervisor import audit, native, quality
from code_supervisor.acceptance import acceptance
from code_supervisor.tasks import CheckError

ROOT = Path(__file__).resolve().parents[1]


def output(tmp_path):
    """创建单独的证据输出目录。"""
    folder = tmp_path / "evidence"
    folder.mkdir()
    return folder


def python_case(tmp_path, weak=False):
    """生成有真实断言或故意弱断言的位移测试工程。"""
    root = tmp_path / "project"
    root.mkdir()
    (root / "calc.py").write_text(
        '"""计算位移。"""\ndef distance(a: float,b: float)->float:\n    """返回位移。"""\n    return b-a\n'
    )
    assertion = (
        "assert distance(1, 3) is not None" if weak else "assert distance(1, 3) == 2"
    )
    (root / "test_calc.py").write_text(
        "from calc import distance\ndef test_distance():\n    " + assertion + "\n"
    )
    files = {"calc.py": "python", "test_calc.py": "python"}
    options = dict(
        files=["calc.py"],
        inputs=["calc.py", "test_calc.py"],
        pytest_args=["test_calc.py"],
        max_mutants=10,
        mutant_timeout=10,
    )
    return root, files, options


def test_crapper_uses_actual_coverage(tmp_path):
    """原版函数与本轮执行覆盖率匹配，完整覆盖函数得到可计算分数。"""
    root, files, options = python_case(tmp_path)
    result = quality.crapper(root, files, options, output(tmp_path))
    assert result["status"] == "pass"
    data = json.loads(Path(result["evidence"]).read_text())
    assert data[0]["coverage"] == 100
    assert data[0]["crap"] == 1


@pytest.mark.parametrize("weak,expected", [(False, "pass"), (True, "fail")])
def test_original_mutator_exposes_weak_assertions(tmp_path, weak, expected):
    """同一原版减法变异被强断言发现，但会逃过弱断言。"""
    root, files, options = python_case(tmp_path, weak)
    before = (root / "calc.py").read_bytes()
    result = quality.mutator(root, files, options, output(tmp_path))
    assert result["status"] == expected, result
    assert result["executed"] == 1
    assert (root / "calc.py").read_bytes() == before


def test_dryer_zero_exit_is_not_assumed_clean(tmp_path):
    """原版结构候选被转换为问题状态，不依赖其退出码。"""
    source = "def first(values):\n    kept = list(values)\n    total = sum(kept)\n    return total + len(kept)\n\ndef second(items):\n    data = list(items)\n    value = sum(data)\n    return value + len(data)\n"
    (tmp_path / "dup.py").write_text(source)
    result = quality.dryer(
        tmp_path,
        {"dup.py": "python"},
        {"min_lines": 1, "min_nodes": 1},
        output(tmp_path),
    )
    assert result["status"] == "fail"
    assert result["findings"]


def test_missing_coverage_cannot_pass(tmp_path):
    """测试通过但没有执行选定源码时，复杂度覆盖检查拒绝通过。"""
    root, files, options = python_case(tmp_path)
    (root / "test_calc.py").write_text("def test_empty():\n    assert True\n")
    with pytest.raises(CheckError, match="未执行"):
        quality.crapper(root, files, options, output(tmp_path))


def test_pyright_detects_wrong_return_type(tmp_path):
    """真实类型分析发现声明与实际返回值不同。"""
    (tmp_path / "bad.py").write_text('def answer() -> int:\n    return "wrong"\n')
    result = audit.pyright(tmp_path, {"bad.py": "python"}, {}, output(tmp_path))
    assert result["status"] == "fail"
    assert result["findings"]


def test_dependency_rule_resolves_relative_import(tmp_path):
    """禁止规则覆盖相对导入，不将相似模块名前缀误判为相同模块。"""
    core = tmp_path / "core"
    core.mkdir()
    (core / "__init__.py").write_text("from . import api\n")
    result = audit.dependencies(
        tmp_path,
        {"core/__init__.py": "python"},
        {"forbidden": [{"from": "core", "to": "core.api"}]},
        output(tmp_path),
    )
    assert result["status"] == "fail"
    assert not audit.prefix_matches("core_extra", "core")


def test_bandit_detects_dynamic_eval(tmp_path):
    """真实源码安全检查能够发现动态 eval。"""
    (tmp_path / "bad.py").write_text(
        "def execute(user_input):\n    return eval(user_input)\n"
    )
    result = audit.security(tmp_path, {"bad.py": "python"}, {}, output(tmp_path))
    assert any(f["rule"] == "B307" for f in result["findings"])


def test_secret_value_is_not_in_report(tmp_path):
    """疑似测试凭据只报告类型和位置，不泄漏原文。"""
    fake = "not-a-real-" + "password-12345678"
    (tmp_path / "settings.env").write_text('password="' + fake + '"\n')
    result = audit.secrets(tmp_path, {}, dict(paths=["settings.env"]), output(tmp_path))
    assert result["status"] == "fail", result
    assert fake not in json.dumps(result)


def test_doxygen_reports_wrong_parameter(tmp_path):
    """官方 Doxygen 能发现注释参数与实际签名不符。"""
    (tmp_path / "api.hh").write_text(
        "/** @file api.hh\n * @brief 接口。\n */\n/** @brief 计算。\n * @param wrong 错误名称。\n * @return 结果。\n */\nint value(int actual);\n"
    )
    result = native.doxygen(tmp_path, {"api.hh": "cpp"}, {}, output(tmp_path))
    assert result["status"] == "fail"
    assert any("wrong" in f["message"] for f in result["findings"])


def test_cpp_real_build_coverage_and_mutation(tmp_path):
    """真正重新编译 C++ 变异，再用测试捕获算术变化。"""
    root = ROOT / "examples/cpp-demo"
    files = {"distance.hh": "cpp", "test_distance.cc": "cpp"}
    options = dict(
        inputs=["distance.hh", "test_distance.cc", "CMakeLists.txt"],
        files=["distance.hh"],
        max_mutants=10,
    )
    result = native.cpp_mutation(root, files, options, output(tmp_path))
    assert result["status"] == "pass", result
    assert result["executed"] >= 1


def test_acceptance_validates_metrics_and_checks(tmp_path):
    """业务验收即使退出0，失败判据和超限指标仍然失败。"""
    root = tmp_path / "project"
    root.mkdir()
    data = {"checks": {"stopped": False}, "metrics": {"duration": 3}}
    (root / "accept.py").write_text(
        'import json\nopen("result.json","w").write(' + repr(json.dumps(data)) + ")\n"
    )
    options = dict(
        inputs=["accept.py"],
        argv=["{python}", "accept.py"],
        report="result.json",
        limits={"duration": 2},
    )
    result = acceptance(root, {}, options, output(tmp_path))
    assert result["status"] == "fail"
    assert len(result["findings"]) == 2


def test_old_acceptance_report_rejected(tmp_path):
    """复制进来的旧报告不能被用作本轮验收。"""
    (tmp_path / "result.json").write_text('{"checks":{"ok":true}}')
    with pytest.raises(CheckError, match="旧结果"):
        acceptance(
            tmp_path,
            {},
            dict(
                inputs=["result.json"],
                argv=[sys.executable, "-c", "pass"],
                report="result.json",
            ),
            output(tmp_path),
        )


def test_good_doxygen_has_no_false_missing_parameter_warning(tmp_path):
    """同时生成 HTML/XML，避免 Doxygen 1.9.8 只生成 XML 时的假缺文档警告。"""
    root = ROOT / "examples/cpp-demo"
    result = native.doxygen(
        root, {"distance.hh": "cpp", "test_distance.cc": "cpp"}, {}, output(tmp_path)
    )
    assert result["status"] == "pass", result


def test_cpp_coverage_excludes_generated_compiler_probes(tmp_path):
    """覆盖率只统计所选业务头文件，CMake 编译器探针和测试不混入分母。"""
    root = ROOT / "examples/cpp-demo"
    result = native.cpp_coverage(
        root,
        {"distance.hh": "cpp"},
        dict(
            files=["distance.hh"],
            inputs=["distance.hh", "test_distance.cc", "CMakeLists.txt"],
            minimum=100,
        ),
        output(tmp_path),
    )
    assert result["coverage"] == 100
    assert result["status"] == "pass"


def test_acceptance_contradictory_exit_is_error(tmp_path):
    """执行失败却报告全通过时不能通过门禁。"""
    (tmp_path / "case.py").write_text(
        'import json\nopen("result.json","w").write(json.dumps({"checks":{"ok":True}}))\nraise SystemExit(1)\n'
    )
    with pytest.raises(CheckError, match="命令失败"):
        acceptance(
            tmp_path,
            {},
            dict(
                inputs=["case.py"], argv=["{python}", "case.py"], report="result.json"
            ),
            output(tmp_path),
        )


def test_snapshot_does_not_follow_top_level_symlink(tmp_path):
    """隔离输入不能通过顶层链接绕过副本边界。"""
    from code_supervisor.tasks import snapshot

    (tmp_path / "a.py").write_text("value=1")
    (tmp_path / "b.py").symlink_to(tmp_path / "a.py")
    with pytest.raises(CheckError, match="符号链接"):
        snapshot(tmp_path, output(tmp_path), dict(inputs=["b.py"]))


def test_sarif_keeps_incomplete_state():
    """SARIF 不把无诊断但检查失败的运行标为成功。"""
    from code_supervisor.reporting import sarif, compare_reports

    report = dict(
        root="/tmp/project",
        version="0.2.0",
        exit_code=2,
        results=[dict(id="build", status="error", reason="no compiler")],
    )
    run = sarif(report)["runs"][0]
    assert not run["invocations"][0]["executionSuccessful"]
    assert run["invocations"][0]["toolExecutionNotifications"]
    assert not compare_reports(report, report)["added"]


def test_carriage_summary_requires_complete_consistent_results():
    """车辆协议拒绝不完整或与工况矛盾的汇总。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "carriage_suite", ROOT / "scripts/carriage_suite.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = dict(complete=True, passed=True, results={"brake": {"passed": True}})
    assert module.convert_summary(data)["checks"] == {"brake": True}
    data["passed"] = False
    with pytest.raises(ValueError, match="矛盾"):
        module.convert_summary(data)
    data["complete"] = False
    with pytest.raises(ValueError, match="完整"):
        module.convert_summary(data)
