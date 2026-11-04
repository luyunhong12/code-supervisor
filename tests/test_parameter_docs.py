"""参数注释规则的正例、反例与配置快照测试。"""

from pathlib import Path
import pytest
from code_supervisor.parameter_docs import (
    python_parameters,
    cpp_parameters,
    yaml_parameters,
    parameter_docs,
)


def test_python_all_argument_kinds():
    """位置限定、关键字限定及变长参数均须按名字关联说明。"""
    source = '''def f(a, /, b=1, *args, c, **kwargs):
    """执行。

    Args:
        a: 输入。
        b (int): 次数。
        *args: 扩展位置参数。
        c:
            必填关键字。
        **kwargs: 扩展选项。
    """
    pass
'''
    rows, skipped = python_parameters(source)
    assert {r["parameter"] for r in rows} == {"a", "b", "args", "c", "kwargs"}
    assert all(r["description"] for r in rows)
    assert not skipped


def test_python_does_not_borrow_unrelated_prose():
    """摘要中出现参数名或另一个参数的说明不能替代对应Args条目。"""
    rows, _ = python_parameters(
        'def f(x,y):\n    """x输入，y输出。\n\n    Args:\n        x: 输入。\n    """\n    pass\n'
    )
    assert [r["parameter"] for r in rows if not r["description"]] == ["y"]


def test_method_receivers_and_static_self():
    """仅真实方法接收者可豁免，静态函数和模块函数的self仍需说明。"""
    rows, exceptions = python_parameters(
        "class C:\n def f(self, x): pass\n @classmethod\n def g(cls,y): pass\n @staticmethod\n def h(self): pass\ndef z(self): pass\n"
    )
    assert len(exceptions) == 2
    assert [r["parameter"] for r in rows] == ["self", "x", "y", "self"]


def test_constructor_uses_class_args():
    """构造器缺少独立文档时允许Google类文档中的参数说明。"""
    rows, _ = python_parameters(
        'class C:\n """对象。\n\n Args:\n     x: 输入值。\n """\n def __init__(self,x): pass\n'
    )
    assert rows[0]["description"] == "输入值。"


def test_cpp_declaration_definition_and_callback():
    """声明和实现分别检查，指针形参也不能漏过。"""
    source = b"/** @param[in] x value */\nint f(int x);\n/** @param x \xe8\xbe\x93\xe5\x85\xa5\xe3\x80\x82\n * @param callback \xe5\x9b\x9e\xe8\xb0\x83\xe3\x80\x82 */\nint f(int x, void (*callback)(int)) {return x;}\n"
    rows, _, complete = cpp_parameters(source)
    assert complete
    assert [r["parameter"] for r in rows] == ["x", "x", "callback"]
    assert rows[0]["description"] == "value"
    assert rows[2]["description"] == "回调。"


def test_cpp_parse_error_is_not_clean():
    """无法完整解析的宏语法不能算作参数检查通过。"""
    assert not cpp_parameters(b"class C { Q_PROPERTY(int x READ x) };")[2]


def test_yaml_specific_comments_and_hash_in_string():
    """文件头不覆盖后续键，字符串内井号不算注释。"""
    rows = yaml_parameters('# 首项用途\na: 1\nb: "#不是注释"\nc: 3 # 时长，秒\n')
    assert rows[0]["description"] == "首项用途"
    assert not rows[1]["description"]
    assert "时长" in rows[2]["description"]


def test_yaml_nested_flow_and_block_scalar():
    """容器说明不代替子键说明，多行字符串内容不伪装成注释。"""
    rows = yaml_parameters(
        "# 容器\na:\n  # 子项\n  b: 1\n  c: {d: 2}\ntext: |\n  # 内容\nnext: 1\n"
    )
    docs = {r["parameter"]: r["description"] for r in rows}
    assert docs["a.b"] == "子项"
    assert not docs["a.c.d"]
    assert not docs["next"]


@pytest.mark.parametrize("source", ["a: 1\na: 2", "a: &a {b: *a}"])
def test_yaml_invalid_mapping_rejected(source):
    """重复键和循环别名不能因遍历遗漏而通过。

    Args:
        source: 故意构造的无效映射文本。
    """
    with pytest.raises(ValueError):
        yaml_parameters(source)


def test_adapter_reports_missing_parameter_and_unsupported_config(tmp_path):
    """跨语言汇总保留缺失项、配置哈希以及不支持格式。

    Args:
        tmp_path: 隔离测试目录。
    """
    (tmp_path / "a.py").write_text("def f(x): pass\n")
    (tmp_path / "a.yaml").write_text("x: 1\n")
    (tmp_path / "a.json").write_text('{"x":1}')
    output = tmp_path / "out"
    output.mkdir()
    result = parameter_docs(
        tmp_path, {"a.py": "python"}, dict(paths=["a.yaml", "a.json"]), output
    )
    assert result["status"] == "error"
    assert len(result["findings"]) == 2
    assert result["unparsed"][0]["file"] == "a.json"
    assert Path(result["evidence"]).exists()


def test_qt_properties_do_not_hide_real_parameters():
    """元对象宏不产生伪形参，后续真实参数仍按原行号检查。"""
    source = b"class C {\n Q_OBJECT\n Q_PROPERTY(QString speed READ Speed NOTIFY Updated)\n signals:\n void command(int value);\n};"
    rows, exceptions, complete = cpp_parameters(source)
    assert complete and not exceptions
    assert [(r["line"], r["parameter"], r["description"]) for r in rows] == [
        (5, "value", "")
    ]


@pytest.mark.parametrize(
    "macro",
    ["Q_PROPERTY(int x READ x", "Q_PROPERTY(int x UNKNOWN x)", "UNKNOWN_MACRO(int x)"],
)
def test_unsupported_meta_syntax_remains_visible(macro):
    """不闭合及不认识的元语法仍返回解析失败，不能整体跳过头文件。

    Args:
        macro: 不完整或不支持的独立宏声明。
    """
    assert not cpp_parameters(("class C {\n" + macro + "\n};").encode())[2]


def test_qt_mask_keeps_literal_and_comment_bytes():
    """字符串和块注释中的宏样文本不可改写。"""
    from code_supervisor.parameter_docs import qt_parameter_source

    source = b'const char *s = R"(\nQ_OBJECT\n)";\n/*\nQ_OBJECT\n*/'
    assert qt_parameter_source(source) == source
