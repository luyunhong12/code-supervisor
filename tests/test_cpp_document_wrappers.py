"""文档关联只穿过透明语法包装，不借用外层类型或其他函数注释。"""

from code_supervisor.cpp import cpp_docs
from code_supervisor.parameter_docs import cpp_parameters


def test_nested_type_and_linkage_docs(tmp_path):
    """嵌套结构体与单函数extern C应找到紧邻包装前的说明。

    Args:
        tmp_path: pytest独立目录，保存待扫描的C++样例。
    """
    source = """/** @file
 * @brief 文档测试。
 */
/** @brief 外层类型。 */
class Outer {
    /** @brief 内层状态。 */
    struct Inner {};
};
/** @brief 输入转换。
 * @param value 输入整数。
 */
extern "C" int convert(int value) { return value; }
"""
    (tmp_path / "sample.hh").write_text(source)
    result = cpp_docs(tmp_path, ["sample.hh"])
    assert result["status"] == "pass", result
    assert result["definitions"] == 3
    rows, _, complete = cpp_parameters(source.encode())
    assert complete
    assert rows[0]["description"] == "输入整数。"


def test_linkage_block_does_not_document_its_children(tmp_path):
    """链接块注释不能冒充块内所有函数的说明。

    Args:
        tmp_path: pytest独立目录，保存缺少函数说明的样例。
    """
    source = """/** @file
 * @brief 文档测试。
 */
/** @brief 链接块说明。
 * @param value 不是内部函数的参数契约。
 */
extern "C" {
 int convert(int value) { return value; }
}
"""
    (tmp_path / "sample.hh").write_text(source)
    result = cpp_docs(tmp_path, ["sample.hh"])
    assert result["status"] == "fail"
    rows, _, complete = cpp_parameters(source.encode())
    assert complete
    assert rows[0]["description"] == ""
