"""编译器扩展适配不能遮蔽真实函数形参或未知语法错误。"""

import pytest

from code_supervisor.parameter_docs import cpp_parameters


@pytest.mark.parametrize(
    "extension",
    [
        "GZ_ADD_PLUGIN(Demo, Base)\n",
        "GZ_PHYSICS_ADD_PLUGIN(Demo, Policy, Features)\n",
        'GZ_ADD_PLUGIN_ALIAS(Demo, "alias")\n',
        "/** @param value 输入值。 */\nvoid f(int value) { (object->*method)(value); }\n",
        "/** @param value 输入值。 */\nextern int f(int value) asm(SYMBOL);\n",
    ],
)
def test_supported_extensions_keep_real_parameters(extension):
    """登记宏与表达式适配不丢失函数参数及中文注释。

    Args:
        extension: 单个已支持语法结构的完整源码片段。
    """
    source = extension + "/** @param count 数量。 */\nvoid ordinary(int count);\n"
    rows, _, complete = cpp_parameters(source.encode())
    assert complete
    assert rows[-1]["parameter"] == "count"
    assert "数量" in rows[-1]["description"]
    if "int value" in extension:
        assert rows[0]["parameter"] == "value"
        assert "输入值" in rows[0]["description"]


@pytest.mark.parametrize(
    "source",
    [
        "UNKNOWN_REGISTRATION(Demo)\n",
        "void broken(int value { }",
        "void f() { (object->*)(0); }",
        "extern int f(int value) asm(BAD + SYMBOL);",
    ],
)
def test_unknown_errors_remain_visible(source):
    """未识别的注册宏、声明和表达式不能被适配成检查通过。

    Args:
        source: 包含未支持或无效语法的源码。
    """
    assert not cpp_parameters(source.encode())[2]
