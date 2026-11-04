"""读取JSON/XML配置参数，并将逐路径Markdown说明关联到真实字段。"""

import json
import re
from xml.parsers import expat


def json_parameters(source):
    """枚举JSON映射键，数组标量由所属键说明，拒绝重复键。

    Args:
        source: JSON文本，不接受注释或重复键。
    """

    def mapping(pairs):
        """保留JSON对象并拒绝覆盖同名字段。

        Args:
            pairs: 解码器提供的有序键值对。
        """
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"JSON重复字段：{key}")
            result[key] = value
        return result

    rows = []

    def visit(value, path):
        """递归枚举对象和数组内的字段，使用JSON Pointer转义。

        Args:
            value: 当前JSON值。
            path: 当前对象的绝对参数路径。
        """
        if isinstance(value, dict):
            for key, child in value.items():
                name = path + "/" + key.replace("~", "~0").replace("/", "~1")
                rows.append(
                    dict(line=1, parameter=name, description="", owner="JSON配置")
                )
                visit(child, name)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}/{index}")

    visit(json.loads(source, object_pairs_hook=mapping), "")
    return rows


def xml_parameters(source):
    """枚举XML元素和属性，记录实际行号；禁止DTD及外部实体。

    Args:
        source: XML文本，重复同名元素用零基同名兄弟序号区分。
    """
    parser = expat.ParserCreate()
    stack = []
    counts = [{}]
    rows = []

    def start(name, attributes):
        """记录元素及每个属性，不把容器说明自动分配给子参数。

        Args:
            name: 元素标签。
            attributes: 元素属性名到字符串值的映射。
        """
        index = counts[-1].get(name, 0)
        counts[-1][name] = index + 1
        path = (stack[-1] if stack else "") + f"/{name}[{index}]"
        stack.append(path)
        counts.append({})
        rows.append(
            dict(
                line=parser.CurrentLineNumber,
                parameter=path,
                description="",
                owner="XML配置",
            )
        )
        for key in attributes:
            rows.append(
                dict(
                    line=parser.CurrentLineNumber,
                    parameter=path + "/@" + key,
                    description="",
                    owner="XML配置",
                )
            )

    def end(name):
        """离开当前元素，恢复父元素的路径与计数。

        Args:
            name: 已匹配的结束标签；解析器保证与开始标签一致。
        """
        stack.pop()
        counts.pop()

    def reject_doctype(*arguments):
        """拒绝DTD，避免隐式默认属性和实体改变被检查配置。

        Args:
            arguments: Expat传入的声明参数，不解析其内容。
        """
        raise ValueError("配置参数检查不接受DTD或外部实体")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = reject_doctype
    parser.Parse(source, True)
    return rows


def markdown_descriptions(source):
    """读取两列参数表；星号只匹配一个路径段，重复路径明确拒绝。

    Args:
        source: 包含“参数路径 | 中文说明”表格的Markdown文本。
    """
    result = {}
    for line in source.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [part.strip().strip("`") for part in line.strip().strip("|").split("|")]
        if len(cells) != 2 or not cells[0].startswith("/"):
            continue
        if cells[0] in result:
            raise ValueError(f"参数说明路径重复：{cells[0]}")
        result[cells[0]] = cells[1]
    if not result:
        raise ValueError("参数说明文档没有有效的逐路径两列表格")
    return result


def attach_descriptions(rows, descriptions):
    """匹配逐路径说明，拒绝未用到或有歧义的规则，不自动豁免缺少说明。

    Args:
        rows: 从实际配置解析的参数记录，原地补充说明。
        descriptions: Markdown路径到中文说明的映射；*匹配一个非空路径片段。
    """
    patterns = {
        key: re.compile(re.escape(key).replace(r"\*", "[^/]+") + r"\Z")
        for key in descriptions
    }
    used = set()
    for row in rows:
        matches = [
            key
            for key, pattern in patterns.items()
            if pattern.fullmatch(row["parameter"])
        ]
        if len(matches) > 1:
            raise ValueError(f"参数说明规则重叠：{row['parameter']}")
        if matches:
            key = matches[0]
            row["description"] = descriptions[key]
            used.add(key)
    unused = set(descriptions) - used
    if unused:
        raise ValueError("参数说明包含不存在的路径：" + ", ".join(sorted(unused)))
    return rows
