"""逐路径配置说明必须覆盖真实键，不能靠泛泛文档或解析遗漏通过。"""

import hashlib
import json
from pathlib import Path

import pytest
from code_supervisor.configuration_docs import (
    attach_descriptions,
    json_parameters,
    markdown_descriptions,
    xml_parameters,
)
from code_supervisor.parameter_docs import parameter_docs


def test_json_arrays_and_pointer_escaping():
    """每个数组对象独立列出字段，斜线和波浪号使用JSON Pointer转义。"""
    rows = json_parameters('{"parts":[{"a/b":1},{"a/b":2}],"~key":3}')
    docs = markdown_descriptions(
        "| /parts | 零件列表。 |\n| /parts/*/a~1b | 零件数值。 |\n| /~0key | 标记。 |"
    )
    attach_descriptions(rows, docs)
    assert [r["parameter"] for r in rows] == [
        "/parts",
        "/parts/0/a~1b",
        "/parts/1/a~1b",
        "/~0key",
    ]
    assert all(r["description"] for r in rows)


def test_json_duplicate_keys_rejected():
    """后一个同名键不得覆盖前一个而隐藏配置参数。"""
    with pytest.raises(ValueError, match="重复"):
        json_parameters('{"x":1,"x":2}')


def test_xml_elements_attributes_and_lines():
    """XML每个同名兄弟与属性独立列出，值中的符号不冒充注释。"""
    rows = xml_parameters(
        '<gui enabled="true">\n <item x="1"/>\n <item x="2"/>\n</gui>'
    )
    assert [(r["parameter"], r["line"]) for r in rows] == [
        ("/gui[0]", 1),
        ("/gui[0]/@enabled", 1),
        ("/gui[0]/item[0]", 2),
        ("/gui[0]/item[0]/@x", 2),
        ("/gui[0]/item[1]", 3),
        ("/gui[0]/item[1]/@x", 3),
    ]


def test_xml_doctype_rejected():
    """实体或隐式属性不能改变参数扫描含义，也不读取外部文件。"""
    with pytest.raises(ValueError, match="DTD"):
        xml_parameters('<!DOCTYPE a [<!ENTITY x SYSTEM "file:///not-read">]><a>&x;</a>')


@pytest.mark.parametrize(
    "docs",
    [
        {"/typo": "错误路径。"},
        {"/x": "具体说明。", "/*": "重叠说明。"},
    ],
)
def test_unused_or_ambiguous_rules_rejected(docs):
    """拼错路径或范围交叠时明确报错，不默默接受无效文档。

    Args:
        docs: 包含未使用或重叠规则的参数说明。
    """
    with pytest.raises(ValueError):
        attach_descriptions(json_parameters('{"x":1}'), docs)


def test_documentation_does_not_cover_new_keys():
    """新增字段没有自己的路径说明时保持缺注释状态。"""
    rows = attach_descriptions(json_parameters('{"x":1,"new":2}'), {"/x": "已有字段。"})
    assert rows[1]["description"] == ""


def test_duplicate_document_paths_rejected():
    """同一路径不能由后面的文档行静默覆盖。"""
    with pytest.raises(ValueError, match="重复"):
        markdown_descriptions("| /x | 一。 |\n| /x | 二。 |")


def test_adapter_hashes_documentation_and_reports_missing(tmp_path):
    """真实适配器保存说明文档哈希，未说明的键继续报告。

    Args:
        tmp_path: 独立配置、文档及证据目录。
    """
    (tmp_path / "a.json").write_text('{"x":1,"new":2}')
    document = "| /x | 原字段，无量纲。 |\n"
    (tmp_path / "parameters.md").write_text(document)
    options = {"paths": ["a.json"], "documentation": {"a.json": "parameters.md"}}
    (tmp_path / "out").mkdir()
    result = parameter_docs(tmp_path, {}, options, tmp_path / "out")
    assert result["status"] == "fail"
    assert len(result["findings"]) == 1
    assert "/new" in result["findings"][0]["message"]
    evidence = json.loads(Path(result["evidence"]).read_text())
    assert (
        evidence["hashes"]["parameters.md"]
        == hashlib.sha256(document.encode()).hexdigest()
    )


@pytest.mark.parametrize("value", [[], {"a.json": 1}, {"": "doc.md"}, {"a.json": ""}])
def test_documentation_option_rejects_invalid_mapping(value):
    """配置边界拒绝错误的文档映射类型，不能等到扫描时才崩溃。

    Args:
        value: 无效的配置到Markdown路径映射。
    """
    from code_supervisor.adapters import validate_settings

    with pytest.raises(ValueError, match="documentation"):
        validate_settings({"parameter-docs": {"paths": [], "documentation": value}})
