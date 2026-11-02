"""用 C++ 语法树检查 Doxygen 基本文档，不执行编译或推断契约。"""

import importlib.metadata
import re

from .checks import CHINESE, finding


def nodes(node):
    """深度遍历语法树，返回全部节点。"""
    yield node
    for child in node.named_children:
        yield from nodes(child)


def preceding(node, source):
    """读取定义前紧邻的 Doxygen 块或连续 /// 行，允许模板包装。"""
    if node.parent and node.parent.type == "template_declaration":
        node = node.parent
    previous = node.prev_named_sibling
    comments = []
    end = node.start_byte
    while previous and previous.type == "comment":
        if source[previous.end_byte : end].strip():
            break
        text = previous.text.decode("utf-8")
        if not (text.startswith("/**") or text.startswith("///")):
            break
        if re.search(r"[@\\]file\b", text):
            break
        comments.insert(0, text)
        end = previous.start_byte
        previous = previous.prev_named_sibling
    return "\n".join(comments)


def targets(tree):
    """提取函数声明/定义及有主体的类型，排除函数局部变量声明。"""
    for node in nodes(tree.root_node):
        if node.type in {"class_specifier", "struct_specifier", "enum_specifier"}:
            if node.child_by_field_name("body"):
                yield node
        elif node.type == "function_definition":
            yield node
        elif node.type in {"declaration", "field_declaration"}:
            declarator = node.child_by_field_name("declarator")
            if declarator and declarator.type == "function_declarator":
                parent = node.parent
                while parent and parent.type != "function_definition":
                    parent = parent.parent
                if parent is None:
                    yield node


def cpp_docs(root, files):
    """检查文件、可解析类型和函数的中文 Doxygen 概述。

    Args:
        root: 项目根目录。
        files: 已选定的 C/C++ 相对路径列表。

    Returns:
        状态与诊断。存在无法解析的文件时为 error，已发现的问题仍保留。
        本检查不替代 Doxygen 官方生成器或编译器，不检查宏展开后的接口、
        参数对应、成员单位及文档真实性；这些进入人工审查。
    """
    from tree_sitter import Language, Parser
    import tree_sitter_cpp

    parser = Parser(Language(tree_sitter_cpp.language()))
    issues = []
    errors = []
    count = 0
    for file in files:
        source = (root / file).read_bytes()
        tree = parser.parse(source)
        if tree.root_node.has_error:
            errors.append(file)
        comments = [
            n.text.decode("utf-8") for n in nodes(tree.root_node) if n.type == "comment"
        ]
        documented = any(
            c.startswith(("/**", "///"))
            and re.search(r"[@\\]file\b", c)
            and re.search(r"[@\\]brief\b", c)
            and CHINESE.search(c)
            for c in comments
        )
        if not documented:
            issues.append(
                finding(
                    file, 1, "CPP-FILE", "缺少含中文 @file/@brief 的 Doxygen 文件说明"
                )
            )
        for node in targets(tree):
            count += 1
            doc = preceding(node, source)
            if not doc or not CHINESE.search(doc):
                issues.append(
                    finding(
                        file,
                        node.start_point.row + 1,
                        "CPP-DOC",
                        "类型/函数声明或定义前缺少紧邻的中文 Doxygen 说明",
                    )
                )
            elif doc.startswith("/**") and not re.search(r"[@\\]brief\b", doc):
                issues.append(
                    finding(
                        file,
                        node.start_point.row + 1,
                        "CPP-BRIEF",
                        "Doxygen 块缺少 @brief",
                    )
                )
    return {
        "status": "error" if errors else "fail" if issues else "pass",
        "findings": issues,
        "unparsed_files": errors,
        "definitions": count,
        "version": importlib.metadata.version("tree-sitter-cpp"),
        "scope": "Doxygen 文件和定义概述子集；复杂宏可能无法解析，需人工审查；非官方 Doxygen 完整验证",
    }
