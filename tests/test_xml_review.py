"""XML 内联注释、配置范围和历史对比的回归验证。"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from code_supervisor.configuration_docs import xml_parameters, attach_descriptions
from code_supervisor.parameter_docs import config_files, parameter_docs
from code_supervisor.reporting import compare_reports, doctor
from code_supervisor.tasks import CheckError


def test_xml_multiline_attributes_and_children():
    """元素、属性与子参数分别关联，不继承父节点说明。"""
    rows = xml_parameters(
        """<?xml version="1.0"?>
<!--
    定义船体。
    name：连杆标识。
        用于关节引用。
-->
<link name="base">
    <!-- 质量，单位 kg。 -->
    <mass>120</mass>
    <missing/>
</link>"""
    )
    assert rows[0]["description"] == "定义船体。"
    assert rows[1]["description"] == "连杆标识。\n用于关节引用。"
    assert rows[2]["description"] == "质量，单位 kg。"
    assert rows[3]["description"] == ""
    assert rows[2]["line"] == 9


@pytest.mark.parametrize(
    "boundary", ["<a/>", "文本", "<?process x?>", "<![CDATA[内容]]>"]
)
def test_xml_boundaries_do_not_leak_comments(boundary):
    """被其他内容消费或隔断的注释不能借给后续元素。

    Args:
        boundary: 注释与目标元素之间的结构或文本边界。
    """
    rows = xml_parameters("<root><!-- 前项说明。 -->" + boundary + "<target/></root>")
    assert rows[-1]["description"] == ""


def test_xml_child_comment_does_not_escape_parent():
    """容器尾部注释不逃逸到兄弟节点，CDATA 伪注释不算说明。"""
    rows = xml_parameters(
        "<root><a><!-- 内部说明。 --></a><b/><![CDATA[<!-- 假说明 -->]]><c/></root>"
    )
    assert all(not row["description"] for row in rows)


@pytest.mark.parametrize(
    "source",
    [
        "<!-- 非法 -- 注释 --><a/>",
        "<!-- 外层 <!-- 内层 --> --><a/>",
        '<!DOCTYPE a [<!ENTITY x SYSTEM "file:///no-read">]><a>&x;</a>',
        '<!-- 元素。\nx：一个。\nx：重复。 --><a x="1"/>',
    ],
)
def test_xml_invalid_comments_and_dtd_rejected(source):
    """非法语法、重复属性说明及实体声明不能通过。

    Args:
        source: 故意无效的 XML 配置文本。
    """
    with pytest.raises(Exception):
        xml_parameters(source)


def test_xml_namespace_and_legacy_fallback():
    """命名空间属性逐名说明，旧表仅补缺失内容。"""
    rows = xml_parameters(
        '<!-- 元素。\nxmlns:xacro：宏命名空间。 -->\n<robot xmlns:xacro="http://example.test" name="boat"/>'
    )
    attach_descriptions(
        rows, {"/robot[0]": "旧元素说明。", "/robot[0]/@name": "船体名称。"}
    )
    assert rows[0]["description"] == "元素。"
    assert rows[1]["description"] == "宏命名空间。"
    assert rows[2]["description"] == "船体名称。"


@pytest.mark.parametrize(
    "suffix", [".xml", ".sdf", ".urdf", ".xacro", ".world", ".launch"]
)
def test_xml_file_types_and_missing_attribute(tmp_path, suffix):
    """支持的 XML 配置逐个进入检查，新增属性不能借用元素说明。

    Args:
        tmp_path: pytest 提供的独立配置目录。
        suffix: 待验证的 XML 格式后缀。
    """
    name = "model" + suffix
    (tmp_path / name).write_text('<!-- 模型说明。 --><model added="1"/>')
    assert config_files(tmp_path, ["."]) == [name]
    out = tmp_path / "out"
    out.mkdir()
    result = parameter_docs(tmp_path, {}, {"paths": [name]}, out)
    assert result["status"] == "fail"
    assert len(result["findings"]) == 1
    assert "/@added" in result["findings"][0]["message"]


def test_empty_configuration_directory_is_error(tmp_path):
    """显式选中的空配置目录不会报告通过。

    Args:
        tmp_path: pytest 提供的空目录。
    """
    with pytest.raises(CheckError, match="没有可检查"):
        parameter_docs(tmp_path, {}, {"paths": ["."]}, tmp_path)


def test_xml_only_cli(tmp_path):
    """没有 Python/C++ 文件时仍可执行非空 XML 参数检查。

    Args:
        tmp_path: pytest 提供的独立工程目录。
    """
    (tmp_path / "boat.urdf").write_text("<!-- 船体模型。 --><robot/>")
    (tmp_path / "supervisor.toml").write_text(
        'version=1\nsource=["."]\nchecks=["parameter-docs"]\n[settings.parameter-docs]\npaths=["boat.urdf"]\n'
    )
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    done = subprocess.run(
        [sys.executable, "-m", "code_supervisor.cli", "check", str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr + done.stdout
    report = json.loads(
        next((tmp_path / ".generated/supervisor").glob("*/report.json")).read_text()
    )
    assert report["results"][0]["parameter_count"] == 1


@pytest.mark.parametrize(
    "status", [None, "error", "not-run", "not-applicable", "pass", "fail"]
)
def test_compare_requires_completed_check(status):
    """消失的诊断只有在同范围检查完成后才归为已解决。

    Args:
        status: 新报告的检查状态，None 表示检查被移除。
    """
    issue = dict(file="a.py", line=1, rule="DOC", message="缺少说明")
    before = dict(
        root="/project",
        source_unchanged=True,
        results=[dict(id="docs", status="fail", findings=[issue])],
        files={"a.py": "python"},
        config_sha256="same",
    )
    after = dict(
        before, results=[] if status is None else [dict(id="docs", status=status)]
    )
    result = compare_reports(before, after)
    complete = status in {"pass", "fail"}
    assert result["resolved"] == ([issue] if complete else [])
    assert result["unverified"] == ([] if complete else [issue])
    if status is None:
        assert result["statuses"] == [dict(id="docs", before="fail", after=None)]
    after["config_sha256"] = "changed"
    assert compare_reports(before, after)["unverified"] == [issue]


def test_python_doctor_does_not_require_cpp(monkeypatch, capsys):
    """Python 环境检查不探测 C++ 编译器与 jscpd。

    Args:
        monkeypatch: pytest 提供的依赖替换工具。
        capsys: pytest 提供的标准输出捕获工具。
    """

    def available(name):
        """提供模拟工具路径。

        Args:
            name: 被查询的工具名称。
        """
        assert name not in {"cmake", "g++", "jscpd", "node"}
        return "/tools/" + name

    monkeypatch.setattr("code_supervisor.reporting.tool", available)
    assert doctor("python") == 0
    assert "cmake" not in capsys.readouterr().out
