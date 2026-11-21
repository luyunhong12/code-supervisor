"""跨项目报告与真实工作目录的使用边界。"""

import copy
import sys

import pytest

from code_supervisor import config, tasks
from code_supervisor.reporting import compare_reports


def report(lines):
    """构造元信息完整、指定诊断位置的报告。

    Args:
        lines: 同一文件中同类诊断的一基行号列表。
    """
    return dict(
        root="/project/A",
        files={"a.cc": "cpp"},
        config_sha256="same",
        source_unchanged=True,
        results=[
            dict(
                id="cpp-docs",
                status="fail" if lines else "pass",
                findings=[
                    dict(file="a.cc", line=line, rule="CPP-DOC", message="缺少文档")
                    for line in lines
                ],
            )
        ],
    )


@pytest.mark.parametrize("side", ["before", "after"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("root", "/project/B"),
        ("root", None),
        ("root", ""),
        ("files", None),
        ("config_sha256", None),
        ("source_unchanged", False),
        ("source_unchanged", None),
    ],
)
def test_compare_requires_identity_and_valid_snapshots(side, field, value):
    """双方项目身份或有效快照证据不足时，不能宣称问题已解决。

    Args:
        side: 修改旧报告或新报告。
        field: 缺失或不一致的元信息。
        value: 模拟的元信息值。
    """
    before, after = report([10]), report([])
    target = before if side == "before" else after
    if value is None:
        target.pop(field)
    else:
        target[field] = value
    result = compare_reports(before, after)
    assert result["resolved"] == []
    assert result["unverified"] == before["results"][0]["findings"]


@pytest.mark.parametrize("side", ["before", "after"])
def test_snapshot_error_overrides_true_flag(side):
    """快照错误记录不能被相互矛盾的 source_unchanged 标记掩盖。

    Args:
        side: 含快照错误的报告一方。
    """
    before, after = report([10]), report([])
    target = before if side == "before" else after
    target["results"].append(dict(id="snapshot", status="error"))
    result = compare_reports(before, after)
    assert not result["resolved"] and len(result["unverified"]) == 1


@pytest.mark.parametrize(
    "old,new,lost,added",
    [
        ([10, 20], [20], [10], []),
        ([10, 20], [], [10, 20], []),
        ([10], [10, 20], [], [20]),
        ([], [10, 20], [], [10, 20]),
        ([10, 20], [30, 40], [], []),
        ([10, 20], [20, 30], [], []),
        ([10, 10, 10], [10], [10, 10], []),
        ([10], [10, 10, 10], [], [10, 10]),
        ([10, 20], [10, 20], [], []),
        ([], [], [], []),
    ],
)
def test_compare_preserves_multiplicity_and_line_moves(old, new, lost, added):
    """重复诊断按出现次数比较，先配对原位置，再容许行号移动。

    Args:
        old: 旧报告中的行号。
        new: 新报告中的行号。
        lost: 预期消失的诊断原行号。
        added: 预期新增的诊断行号。
    """
    before, after = report(old), report(new)
    originals = copy.deepcopy((before, after))
    result = compare_reports(before, after)
    assert [x["line"] for x in result["resolved"]] == lost
    assert [x["line"] for x in result["added"]] == added
    assert not result["unverified"]
    assert (before, after) == originals


def test_valid_snapshot_status_and_invalid_duplicate_counts():
    """显式通过的快照可比较，失效快照中的重复项全部保留待核实。"""
    before, after = report([10, 20]), report([])
    after["results"].append(dict(id="snapshot", status="pass"))
    assert len(compare_reports(before, after)["resolved"]) == 2
    after["source_unchanged"] = False
    result = compare_reports(before, after)
    assert not result["resolved"] and len(result["unverified"]) == 2


@pytest.mark.parametrize("directory", sorted(config.GENERATED_DIRS))
def test_snapshot_prunes_generated_directories_before_links(tmp_path, directory):
    """扫描与副本共用排除规则，生成目录中的链接不应阻断复制。

    Args:
        tmp_path: 工程及外部输出目录。
        directory: 应提前剪枝的生成目录。
    """
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.py").write_text("pass\n")
    folder = root / directory
    folder.mkdir()
    (folder / "old.py").write_text("pass\n")
    (folder / "python").symlink_to(sys.executable)
    output = tmp_path / "output"
    output.mkdir()
    work = tasks.snapshot(root, output, dict(inputs=["."]))
    assert sorted(p.name for p in work.iterdir()) == ["a.py"]
    assert config.discover(root, dict(source=["."], exclude=[])) == {"a.py": "python"}


def test_snapshot_rejects_ordinary_directory_symlink(tmp_path):
    """普通源码目录的链接仍须拒绝，不能因剪枝优化放宽隔离规则。

    Args:
        tmp_path: 项目和副本目录。
    """
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.py").write_text("pass\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(tasks.CheckError, match="符号链接"):
        tasks.snapshot(root, output, dict(inputs=["."]))


def test_snapshot_retains_vendor_build_inputs(tmp_path):
    """第三方源码可用于构建，但不被当作自有源码扫描。

    Args:
        tmp_path: 工程与副本目录。
    """
    root = tmp_path / "project"
    (root / "vendor").mkdir(parents=True)
    (root / "a.py").write_text("pass\n")
    (root / "vendor/helper.py").write_text("pass\n")
    output = tmp_path / "output"
    output.mkdir()
    work = tasks.snapshot(root, output, dict(inputs=["."]))
    assert (work / "vendor/helper.py").read_bytes() == (
        root / "vendor/helper.py"
    ).read_bytes()
    assert config.discover(root, dict(source=["."], exclude=[])) == {"a.py": "python"}
