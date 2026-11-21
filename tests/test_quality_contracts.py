"""Python 覆盖率与变异执行器的证据、预算及恢复契约。"""

import json
from types import SimpleNamespace

import pytest

from code_supervisor import quality, process
from code_supervisor.tasks import CheckError
from test_tool_contracts import install_runner


@pytest.mark.parametrize(
    "data,expected",
    [
        ({"a.py": {"executed_lines": [1, 2], "missing_lines": []}}, "pass"),
        ({"/outside/a.py": {"executed_lines": [1, 2]}}, "error"),
        ({}, "error"),
    ],
)
def test_measure_requires_copy_coverage(tmp_path, monkeypatch, data, expected):
    """覆盖数据只能来自本次副本，缺少选定文件时明确失败。

    Args:
        tmp_path: 独立源码和输出根目录。
        monkeypatch: 外部执行替换器。
        data: 模拟覆盖文件映射。
        expected: 预期结果。
    """
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.py").write_text("def f():\n return 1\n")
    out = tmp_path / "out"
    out.mkdir()
    calls = install_runner(
        monkeypatch, quality, out, {"coverage.json": {"files": data}}
    )
    options = dict(inputs=["a.py"], pytest_args=["tests"])
    if expected == "error":
        with pytest.raises(CheckError, match="未执行副本"):
            quality.measure(root, {"a.py": "python"}, options, out)
    else:
        work, names, normalized = quality.measure(
            root, {"a.py": "python"}, options, out
        )
        assert work == out / "workspace" and names == ["a.py"] and normalized == data
        assert (
            work / "coverage-supervisor.ini"
        ).read_text() == "[run]\nbranch = True\nrelative_files = False\n"
        assert "-p" in calls[0][0][0] and "no:cacheprovider" in calls[0][0][0]


def test_measure_rejects_missing_inputs_and_bad_pytest_args(tmp_path, monkeypatch):
    """副本须包含选定源码，pytest 参数须是非空字符串数组。

    Args:
        tmp_path: 测试目录。
        monkeypatch: 执行边界替换器。
    """
    (tmp_path / "a.py").write_text("x=1")
    (tmp_path / "other").write_text("")
    for index, value in enumerate([None, [], [1], "tests"]):
        out = tmp_path / f"out{index}"
        out.mkdir()
        with pytest.raises(CheckError, match="pytest_args"):
            quality.measure(
                tmp_path,
                {"a.py": "python"},
                dict(inputs=["a.py"], pytest_args=value),
                out,
            )
    out = tmp_path / "missing"
    out.mkdir()
    with pytest.raises(CheckError, match="未包含"):
        quality.measure(
            tmp_path,
            {"a.py": "python"},
            dict(inputs=["other"], pytest_args=["tests"]),
            out,
        )
    with pytest.raises(CheckError, match="无后缀"):
        quality.python_sources(tmp_path, {"script": "python"}, {})


@pytest.mark.parametrize(
    "score,expected", [(9.0, "pass"), (10.0, "fail"), (None, "error")]
)
def test_crapper_score_and_branch_contract(tmp_path, monkeypatch, score, expected):
    """CRAP 达到阈值报告，未知分数不能冒充数值，分支覆盖不丢失。

    Args:
        tmp_path: 证据目录。
        monkeypatch: 替换实际测量与上游分析器。
        score: 模拟 CRAP 分数。
        expected: 预期状态。
    """
    from crapper.model import Entry

    def measure(*args):
        """提供独立已知的行和分支覆盖事实。

        Args:
            args: 实际测量的调用参数。
        """
        return (
            tmp_path,
            ["a.py"],
            {
                "a.py": dict(
                    executed_lines=[1],
                    missing_lines=[2],
                    executed_branches=[[1, 2]],
                    missing_branches=[[1, 3]],
                )
            },
        )

    def analyze(files, root, bundle):
        """核对传给上游的覆盖协议。

        Args:
            files: 选定源码。
            root: 副本根目录。
            bundle: 上游覆盖率数据结构。
        """
        assert files == [tmp_path / "a.py"] and root == tmp_path
        assert bundle.lcov["a.py"][1] == (1, 1) and bundle.lcov["a.py"][2] == (0, 1)
        assert bundle.lcov["a.py"].branches[1] == (1, 2)
        return [Entry("f", "a", 2, 50.0, score, "a.py", "python")]

    monkeypatch.setattr(quality, "measure", measure)
    monkeypatch.setattr("crapper.analyze.analyze_files", analyze)
    if expected == "error":
        with pytest.raises(CheckError):
            quality.crapper(tmp_path, {"a.py": "python"}, {}, tmp_path)
    else:
        result = quality.crapper(tmp_path, {"a.py": "python"}, {}, tmp_path)
        assert result["status"] == expected and result["functions"] == 1
        if expected == "fail":
            assert (
                result["findings"][0]["line"] == 1
                and "CRAP=10.000" in result["findings"][0]["message"]
            )


@pytest.mark.parametrize(
    "status,covered,budget,invalid,expected,outcomes",
    [
        ("fail", True, 10, False, "pass", ["killed", "killed"]),
        ("pass", True, 10, False, "fail", ["survived", "survived"]),
        ("error", True, 10, False, "error", ["error", "error"]),
        ("fail", False, 10, False, "error", ["uncovered", "uncovered"]),
        ("fail", True, 1, False, "error", ["killed", "budget-exhausted"]),
        ("fail", True, 10, True, "error", ["invalid", "invalid"]),
    ],
)
def test_mutator_classification_and_restoration(
    tmp_path, monkeypatch, status, covered, budget, invalid, expected, outcomes
):
    """分类不能混淆测试失败、执行错误和未完成预算；原文逐次恢复。

    Args:
        tmp_path: 独立变异副本。
        monkeypatch: 测量、变异位置与进程替换器。
        status: 模拟测试执行状态。
        covered: 基线是否执行了变异位置。
        budget: 有效变异预算。
        invalid: 是否生成语法无效的候选。
        expected: 预期最终状态。
        outcomes: 逐项预期分类。
    """
    original = b"def f(x):\n    return x + 1\n"
    path = tmp_path / "a.py"
    path.write_bytes(original)
    position = original.index(b"+")
    sites = [
        SimpleNamespace(
            line=2,
            anchor_line=2,
            start=position,
            end=position + 1,
            original="+",
            mutant=")" if invalid else "-",
            mutation_id=str(index),
        )
        for index in range(2)
    ]

    def measure(*args):
        """返回待变异文件的独立覆盖事实。

        Args:
            args: 测量调用参数。
        """
        return (
            tmp_path,
            ["a.py"],
            {"a.py": {"executed_lines": [1, 2] if covered else []}},
        )

    def candidates(*args):
        """返回明确的候选位置。

        Args:
            args: 上游位置生成参数。
        """
        return sites

    def execute(*args, **kwargs):
        """核对每轮都运行修改过的副本。

        Args:
            args: 测试命令与执行参数。
            kwargs: 失败码分类。
        """
        assert path.read_bytes() == original.replace(b"+", b"-")
        assert kwargs == {"finding_codes": [1]}
        return dict(status=status)

    monkeypatch.setattr(quality, "measure", measure)
    monkeypatch.setattr("mutator.functions.sites_in_file", candidates)
    monkeypatch.setattr(process, "execute", execute)
    result = quality.mutator(
        tmp_path,
        {"a.py": "python"},
        dict(pytest_args=["tests"], max_mutants=budget),
        tmp_path,
    )
    assert result["status"] == expected
    records = json.loads((tmp_path / "mutator.json").read_text())
    assert [row["outcome"] for row in records] == outcomes
    assert path.read_bytes() == original
    assert result["executed"] == sum(
        value in {"killed", "survived", "error"} for value in outcomes
    )
    assert [x["message"] for x in result["findings"]] == [
        value for value in outcomes if value in {"survived", "uncovered"}
    ]
