"""深度变异检查暴露的参数边界与报告行为回归。"""

import importlib.metadata

import pytest

from code_supervisor.configuration_docs import (
    json_parameters,
    xml_parameters,
    markdown_descriptions,
)
from code_supervisor.parameter_docs import (
    google_arguments,
    python_parameters,
    cpp_parameters,
    yaml_parameters,
    parameter_docs,
)
from code_supervisor.reporting import sarif, compare_reports, doctor
from code_supervisor.tasks import CheckError


def test_json_record_location_and_description():
    """JSON 记录使用可报告的一基行号，描述缺省为空。"""
    assert json_parameters('{"value":1}') == [
        dict(line=1, parameter="/value", description="", owner="JSON配置")
    ]


def test_xml_same_indent_prose_is_not_attribute_continuation():
    """属性之后同缩进的文字仍属于元素，不会被属性说明吞掉。"""
    rows = xml_parameters('<!--\n  name：标识。\n  元素用途。\n--><root name="a"/>')
    assert rows[0]["description"] == "元素用途。"
    assert rows[1]["description"] == "标识。"


def test_xml_requires_complete_document():
    """未闭合的根元素即使已有开始事件也不能通过解析。"""
    with pytest.raises(Exception):
        xml_parameters("<!-- 根节点。 --><root>")


@pytest.mark.parametrize(
    "source", ["说明文字", "| /a |", "| /a | 中文 | 多余列 |", "| 标题 | 中文 |"]
)
def test_markdown_requires_real_two_column_paths(source):
    """正文、表头及错误列数不能作为参数说明表。

    Args:
        source: 不含有效路径两列表格的文本。
    """
    with pytest.raises(ValueError, match="没有有效"):
        markdown_descriptions(source)


def test_markdown_ignores_prose_and_keeps_exact_description():
    """表外文字不能成为路径条目，单个合法条目应原样保留。"""
    assert markdown_descriptions(
        "其他说明\n| 参数路径 | 中文说明 |\n| `/a` | 数量。 |\n| /b | 错误 | 多余 |"
    ) == {"/a": "数量。"}


def test_google_prose_and_section_boundaries():
    """Args 之外的缩进文字不冒充参数，续行和分区边界保持清晰。"""
    assert google_arguments("用途。\n    x: 不是参数分区。") == {}
    doc = "用途。\n\nArgs:\n    x: 输入值。\n        单位米。\n    y: 输出值。\nReturns:\n    z: 返回结果。"
    assert google_arguments(doc) == {"x": "输入值。\n单位米。", "y": "输出值。"}
    assert google_arguments("Args:\n    x: 输入。\n    普通同层说明。") == {
        "x": "输入。"
    }


def test_cpp_unnamed_and_void_parameters():
    """未命名参数保留位置与原始类型；void 参数列表没有真实参数。"""
    rows, exceptions, complete = cpp_parameters(b"int f(int);\nint g(void);")
    assert complete and not rows
    assert exceptions == [
        dict(line=1, parameter="int", reason="未命名形参；需人工核对接口说明")
    ]


def test_python_empty_docs_and_nested_function():
    """类和函数没有文档时也不能漏掉参数，嵌套函数不是方法。"""
    rows, skipped = python_parameters(
        "class C:\n def __init__(self,x): pass\n def f(self):\n  def inner(self): pass\n"
    )
    assert [(r["owner"], r["parameter"], r["description"]) for r in rows] == [
        ("__init__", "x", ""),
        ("inner", "self", ""),
    ]
    assert len(skipped) == 2


def test_yaml_sequences_keep_paths_and_lines():
    """序列中的映射键保留独立索引和真实行号。"""
    rows = yaml_parameters("# 列表\nitems:\n  - x: 1 # 第一项\n  - x: 2 # 第二项\n")
    assert [(r["parameter"], r["line"]) for r in rows] == [
        ("items", 2),
        ("items[0].x", 3),
        ("items[1].x", 4),
    ]
    assert rows[1]["description"] == "\n第一项"
    assert rows[2]["description"] == "\n第二项"


def test_adapter_reports_cpp_parse_failure_and_ini(tmp_path):
    """部分 C++ 解析和未实现的配置格式均保留为错误。

    Args:
        tmp_path: 独立源码及证据目录。
    """
    (tmp_path / "a.cpp").write_text("class C { void f( ;")
    (tmp_path / "a.ini").write_text("[a]\nx=1")
    result = parameter_docs(tmp_path, {"a.cpp": "cpp"}, {"paths": ["a.ini"]}, tmp_path)
    assert result["status"] == "error"
    assert {r["file"] for r in result["unparsed"]} == {"a.cpp", "a.ini"}


def test_adapter_rejects_missing_paths_and_empty_scope(tmp_path):
    """调用者必须明确配置范围，空源码加空配置不能通过。

    Args:
        tmp_path: 独立空目录。
    """
    with pytest.raises(CheckError, match="显式配置paths"):
        parameter_docs(tmp_path, {}, {}, tmp_path)
    with pytest.raises(CheckError, match="范围为空"):
        parameter_docs(tmp_path, {}, {"paths": []}, tmp_path)


def test_adapter_detects_config_content_change(tmp_path, monkeypatch):
    """检查中途配置变化必须留下错误证据。

    Args:
        tmp_path: 独立 XML 与证据目录。
        monkeypatch: 替换解析事件以模拟并发修改。
    """
    path = tmp_path / "a.xml"
    path.write_text("<!-- 配置。 --><a/>")

    def parse_then_change(source):
        """在解析完成后模拟外部写入。

        Args:
            source: 原始 XML 文本。
        """
        rows = xml_parameters(source)
        path.write_text("<!-- 改变。 --><a/>")
        return rows

    monkeypatch.setattr(
        "code_supervisor.parameter_docs.xml_parameters", parse_then_change
    )
    result = parameter_docs(tmp_path, {}, {"paths": ["a.xml"]}, tmp_path)
    assert result["status"] == "error"
    assert any("内容变化" in row["reason"] for row in result["unparsed"])


def test_compare_scope_and_selection():
    """配置、文件范围及显式未选中的检查均不能产生已解决结论。"""
    issue = dict(file="a.py", line=1, rule="DOC", message="缺少说明")
    before = dict(
        root="/project",
        source_unchanged=True,
        files={"a.py": "python"},
        config_sha256="old",
        results=[dict(id="docs", status="fail", findings=[issue])],
    )
    after = dict(before, config_sha256="new", results=[dict(id="docs", status="pass")])
    assert compare_reports(before, after)["scope_changed"]
    assert compare_reports(before, after)["unverified"] == [issue]
    after["config_sha256"] = "old"
    after["files"] = {}
    assert compare_reports(before, after)["scope_changed"]
    after["files"] = before["files"]
    after["results"][0]["selected"] = False
    assert compare_reports(before, after)["unverified"] == [issue]


def test_sarif_locations_and_incomplete_notifications():
    """相对与绝对路径正确编码，非正行号修正为1，未选检查只给提示。"""
    findings = [
        dict(file=name, line=line, rule="DOC", message="说明")
        for name, line in [
            ("a b.py", 0),
            ("/tmp/project/a.py", 3),
            ("/tmp/external.py", 2),
            ("", 1),
        ]
    ]
    report = dict(
        root="/tmp/project",
        version="test",
        exit_code=0,
        results=[
            dict(id="docs", status="fail", findings=findings),
            dict(id="later", status="not-run", selected=False),
        ],
    )
    run = sarif(report)["runs"][0]
    locations = [r.get("locations") for r in run["results"]]
    assert locations[0][0]["physicalLocation"] == dict(
        artifactLocation=dict(uri="a%20b.py"), region=dict(startLine=1)
    )
    assert locations[1][0]["physicalLocation"] == dict(
        artifactLocation=dict(uri="a.py"), region=dict(startLine=3)
    )
    assert (
        locations[2][0]["physicalLocation"]["artifactLocation"]["uri"]
        == "file:///tmp/external.py"
    )
    assert locations[3] is None
    assert run["invocations"][0]["executionSuccessful"]
    assert run["invocations"][0]["toolExecutionNotifications"][0]["level"] == "note"


def test_doctor_missing_tools_and_packages(monkeypatch, capsys):
    """工具或包缺失返回错误，不被忽略或标为可用。

    Args:
        monkeypatch: 替换工具与包查询。
        capsys: 捕获环境诊断 JSON。
    """
    import json

    def unavailable(name):
        """模拟未安装的可执行文件。

        Args:
            name: 待查询工具名称。
        """
        raise CheckError(name)

    def missing_package(name):
        """模拟缺失的软件包元信息。

        Args:
            name: 待查询包名称。
        """
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr("code_supervisor.reporting.tool", unavailable)
    monkeypatch.setattr(
        "code_supervisor.reporting.importlib.metadata.version", missing_package
    )
    assert doctor("cpp") == 2
    rows = json.loads(capsys.readouterr().out)
    assert rows and not any(row["available"] for row in rows)
    assert {row["tool"] for row in rows} >= {"cmake", "lizard", "tree-sitter-cpp"}


def test_xml_nested_sibling_paths():
    """三层元素使用直接父节点路径，兄弟计数在不同父节点内独立。"""
    rows = xml_parameters(
        "<root><group><item/><item/></group><group><item/></group></root>"
    )
    assert [row["parameter"] for row in rows] == [
        "/root[0]",
        "/root[0]/group[0]",
        "/root[0]/group[0]/item[0]",
        "/root[0]/group[0]/item[1]",
        "/root[0]/group[1]",
        "/root[0]/group[1]/item[0]",
    ]


def test_duplicate_markdown_error_identifies_path():
    """重复说明错误指向参数路径，而非任意说明文字。"""
    with pytest.raises(ValueError) as error:
        markdown_descriptions("| /name | 名称。 |\n| /name | 第二项。 |")
    assert str(error.value) == "参数说明路径重复：/name"


def test_google_without_section_and_short_prose():
    """缩进文字和单字符摘要都合法，但只有 Args 分区产生参数。"""
    assert google_arguments("    x: 普通缩进文字。") == {}
    assert google_arguments("X\n\nArgs:\n    x: 输入。") == {"x": "输入。"}


def test_class_docs_only_fill_undocumented_constructor():
    """类文档不覆盖构造器自有说明，也不被普通方法借用。"""
    source = '''class C:
    """类说明。

    Args:
        x: 类参数。
    """
    def __init__(self, x):
        """构造。

        Args:
            x: 构造器参数。
        """
    def method(self, x):
        """执行。

        Args:
            x: 普通方法参数。
        """
    def missing(self, x): pass
'''
    rows, _ = python_parameters(source)
    assert {row["owner"]: row["description"] for row in rows} == {
        "__init__": "构造器参数。",
        "method": "普通方法参数。",
        "missing": "",
    }
    rows, _ = python_parameters("callback = lambda x: x")
    assert [(row["owner"], row["parameter"], row["description"]) for row in rows] == [
        ("<lambda>", "x", "")
    ]


def test_yaml_sequence_comments_and_comment_order():
    """序列项前注释按实际缩进关联，多行说明保持原文顺序。"""
    rows = yaml_parameters("items:\n  # 第一行\n  # 第二行\n  - x: 1\n")
    assert rows[1]["parameter"] == "items[0].x"
    assert rows[1]["description"] == "第一行\n第二行"


def test_yaml_multiline_quoted_hash_is_not_comment():
    """跨行字符串中井号不因结束列与当前行重合而被当作注释。"""
    rows = yaml_parameters('x: "#伪注释\n aa"\n')
    assert rows[0]["description"] == ""


def test_config_paths_reject_missing_and_symlinks(tmp_path):
    """显式配置路径必须真实存在且不是符号链接。

    Args:
        tmp_path: 独立配置与链接目录。
    """
    from code_supervisor.parameter_docs import config_files

    with pytest.raises(CheckError, match="不存在或为链接"):
        config_files(tmp_path, ["missing.xml"])
    (tmp_path / "real.xml").write_text("<a/>")
    (tmp_path / "link.xml").symlink_to(tmp_path / "real.xml")
    with pytest.raises(CheckError, match="不存在或为链接"):
        config_files(tmp_path, ["link.xml"])


def test_sarif_selected_defaults_to_error():
    """未显式取消选择的执行错误通知必须保持 error 级别。"""
    report = dict(
        root="/tmp/project",
        version="test",
        exit_code=2,
        results=[dict(id="docs", status="error", reason="解析失败")],
    )
    invocation = sarif(report)["runs"][0]["invocations"][0]
    assert not invocation["executionSuccessful"]
    assert invocation["toolExecutionNotifications"] == [
        dict(level="error", message=dict(text="docs: 解析失败"))
    ]


def test_doctor_keeps_readable_chinese_paths(monkeypatch, capsys):
    """环境报告中的中文工具路径直接可读，不退化成转义序列。

    Args:
        monkeypatch: 替换工具与包查询。
        capsys: 捕获中文环境报告。
    """

    def available(name):
        """返回带中文目录的模拟工具路径。

        Args:
            name: 待查询的工具或包名称。
        """
        return "/工具/" + name

    monkeypatch.setattr("code_supervisor.reporting.tool", available)
    monkeypatch.setattr(
        "code_supervisor.reporting.importlib.metadata.version", available
    )
    assert doctor("all") == 0
    assert "/工具/" in capsys.readouterr().out


def test_xml_indented_attribute_prose_boundary():
    """属性说明可比元素概述缩进更深，同层文字仍不能冒充续行。"""
    rows = xml_parameters(
        '<!--\n概述。\n    name：标识。\n    同层补充。\n--><root name="x"/>'
    )
    assert rows[1]["description"] == "标识。"
    assert rows[0]["description"] == "概述。\n    同层补充。"


def test_google_colon_in_indented_description():
    """参数说明内更深缩进的冒号条目是续行，不是新的函数参数。"""
    assert google_arguments("Args:\n    x: 对象。\n        nested: 内部结构。") == {
        "x": "对象。\nnested: 内部结构。"
    }


def test_isolated_tool_search_order(tmp_path, monkeypatch):
    """隔离命令与工具查找保持相同优先级，源码导入路径仍仅指向副本。

    Args:
        tmp_path: 隔离副本目录。
        monkeypatch: 设置可预测的原始命令搜索路径。
    """
    import os
    from pathlib import Path
    import sys
    from code_supervisor.tasks import clean_python_env
    import code_supervisor.tasks as task_module

    monkeypatch.setenv("PATH", "/existing/tools")
    settings = dict(value.split("=", 1) for value in clean_python_env(tmp_path)[1:])
    bundle = Path(task_module.__file__).resolve().parents[2] / ".tools"
    assert settings["PATH"].split(os.pathsep) == [
        str(Path(sys.executable).parent),
        "/existing/tools",
        str(bundle / "node_modules/.bin"),
        str(bundle),
    ]
    assert settings["PYTHONPATH"].split(os.pathsep) == [
        str(tmp_path),
        str(tmp_path / "src"),
    ]
