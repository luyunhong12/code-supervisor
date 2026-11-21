"""共享保护区间与链接文档边界的独立契约测试。"""

import pytest
from tree_sitter import Language, Parser
import tree_sitter_cpp

from code_supervisor.cpp import (
    overlaps_protected,
    protected_regions,
    preceding,
    targets,
    cpp_parameter_source,
)


@pytest.mark.parametrize(
    "start,end,regions,expected",
    [
        (0, 5, [(5, 10)], False),
        (10, 15, [(5, 10)], False),
        (0, 4, [(5, 10)], False),
        (11, 15, [(5, 10)], False),
        (0, 6, [(5, 10)], True),
        (9, 15, [(5, 10)], True),
        (6, 9, [(5, 10)], True),
        (0, 15, [(5, 10)], True),
        (5, 10, [(5, 10)], True),
        (5, 10, [], False),
        (5, 10, [(0, 5), (10, 15)], False),
        (5, 10, [(0, 5), (9, 15)], True),
    ],
)
def test_protected_interval_contract(start, end, regions, expected):
    """重叠由共同字节决定，覆盖相邻、包含、部分相交和多个保护区间。

    Args:
        start: 候选区间起点。
        end: 候选区间终点。
        regions: 保护字节区间列表。
        expected: 按左闭右开区间规则推导的结果。
    """
    assert overlaps_protected(start, end, regions) is expected


def test_protected_regions_keep_all_literal_forms():
    """只提取注释与各类字符串，不把邻近标识符和数值当作保护文本。"""
    source = b'// note\n/* block */\nconst char* a="normal"; auto b=R"(raw)"; auto c=u8"utf8"; int n=7;'
    tree = Parser(Language(tree_sitter_cpp.language())).parse(source)
    regions = protected_regions(tree)
    assert [source[start:end] for start, end in regions] == [
        b"// note",
        b"/* block */",
        b'"normal"',
        b'R"(raw)"',
        b'u8"utf8"',
    ]


@pytest.mark.parametrize("wrapper", ['extern "C" ', 'extern "C++" '])
def test_linkage_single_target_and_block_boundary(wrapper):
    """单声明继承外部文档，链接块内部目标必须使用自己的文档。

    Args:
        wrapper: C 或 C++ 链接规范前缀。
    """
    source = (
        "/** @brief 单声明。 */\n" + wrapper + "int single();\n"
        "/** @brief 块说明不属于函数。 */\n" + wrapper + "{\n"
        "int missing();\n/** @brief 内部函数。 */\nint inside();\n}\n"
    ).encode()
    tree = Parser(Language(tree_sitter_cpp.language())).parse(source)
    assert not tree.root_node.has_error
    docs = [preceding(node, source) for node in targets(tree)]
    assert docs == ["/** @brief 单声明。 */", "", "/** @brief 内部函数。 */"]


def test_all_adapters_preserve_protected_text():
    """Qt 和成员指针适配共用保护规则，字符串与注释中的伪语法保持原字节。"""
    source = b"""const char* text = R"(
Q_OBJECT
signals:
object->*member
)";
/*
Q_PROPERTY(int x READ x NOTIFY y)
signals:
object->*member
*/
class C {
Q_OBJECT
signals:
void f(){ (object->*member)(); }
};
"""
    adapted = cpp_parameter_source(source)
    marker = source.index(b"class C")
    assert adapted[:marker] == source[:marker]
    assert b"Q_OBJECT" not in adapted[marker:]
    assert b"public :" in adapted[marker:]
    assert b"object.  member" in adapted[marker:]
    assert len(adapted) == len(source)
    assert [i for i, value in enumerate(adapted) if value == 10] == [
        i for i, value in enumerate(source) if value == 10
    ]
