"""隔离副本、证据文件和外部工具调用的公共边界。"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from .config import GENERATED_DIRS, inside
from .process import execute


class CheckError(RuntimeError):
    """检查无法获得可靠证据时使用的错误。"""


def tool(name):
    """优先使用同一虚拟环境内的工具，随后查找 PATH 和独立工具目录。

    Args:
        name: 待查找的工具可执行文件名。
    """
    local = Path(sys.executable).parent / name
    if local.is_file():
        return str(local)
    resolved = shutil.which(name)
    if resolved:
        return resolved
    node = Path(__file__).resolve().parents[2] / ".tools/node_modules/.bin" / name
    if node.is_file():
        return str(node)
    bundled = Path(__file__).resolve().parents[2] / ".tools" / name
    if bundled.is_file():
        return str(bundled)
    raise CheckError(f"缺少工具：{name}")


def run(argv, root, output, label, timeout=120, accepted=(0,)):
    """运行命令并保存日志；非预期退出码抛错，不将工具失败解释为发现问题。

    Args:
        argv: 待执行的程序及参数列表，不通过 shell 解释。
        root: 工程根目录，调用方应传入已解析的绝对路径。
        output: 本次检查的独立输出目录，调用前应已创建。
        label: 日志及相关证据文件的名称前缀。
        timeout: 命令最大等待时间，单位秒。
        accepted: 允许的进程退出码集合，其余退出码视为执行错误。
    """
    log = output / f"{label}.log"
    result = execute(argv, root, log, timeout, finding_codes=())
    if result.get("returncode") not in accepted:
        raise CheckError(
            f'{label} 执行失败：{result.get("reason", result.get("returncode"))}；日志 {log}'
        )
    return log, result["returncode"]


def save(output, name, value):
    """写入单次运行的 JSON 证据，不覆盖业务文件。

    Args:
        output: 本次检查的独立输出目录，调用前应已创建。
        name: 证据文件名，不包含自动添加的 .json 后缀。
        value: 可以序列化为 JSON 的证据内容。
    """
    path = output / (name + ".json")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def selected_files(root, files, options, language):
    """选取适配器明确指定的文件，拒绝范围外或类型不符的路径。

    Args:
        root: 工程根目录，调用方应传入已解析的绝对路径。
        files: 本次扫描得到的相对源码路径到语言的映射。
        options: 当前检查器的配置项，使用其声明的默认值补齐可选项。
        language: 要选取的源码语言标识：python 或 cpp。
    """
    names = options.get("files", [f for f, lang in files.items() if lang == language])
    if not isinstance(names, list) or any(
        not isinstance(f, str) or files.get(f) != language for f in names
    ):
        raise CheckError("files 必须属于本次扫描范围且语言匹配")
    if not names:
        raise CheckError(f"未选定 {language} 源码")
    return names


def snapshot_files(root, path):
    """按公共排除规则提前剪枝，拒绝实际选中源码中的符号链接。

    Args:
        root: 原工程根目录，用于判断相对路径的各级目录。
        path: 本次递归处理的工程内文件或目录，不跟随符号链接。
    """
    if any(part in GENERATED_DIRS for part in path.relative_to(root).parts):
        return
    if path.is_symlink():
        raise CheckError(f"副本输入含符号链接：{path}")
    if path.is_dir():
        for child in sorted(path.iterdir()):
            yield from snapshot_files(root, child)
    elif path.is_file():
        yield path


def snapshot(root, output, options):
    """复制显式输入到新目录；拒绝符号链接，防止变异写入原项目。

    Args:
        root: 原工程根目录。
        output: 单次运行的输出目录。
        options: inputs 为需复制的相对文件或目录列表。

    Returns:
        新副本目录。所有测试、构建和变异均须在此目录执行。

    Raises:
        CheckError: 输入缺失、越界、为符号链接或包含输出目录。
    """
    names = options.get("inputs")
    if not isinstance(names, list) or not names:
        raise CheckError("须配置 inputs，列出隔离测试所需源码、测试和构建文件")
    target = output / "workspace"
    target.mkdir()
    manifests = {}
    for name in names:
        if (root / name).is_symlink():
            raise CheckError(f"副本输入为符号链接：{name}")
        path = inside(root, name)
        if not path.exists() or output.is_relative_to(path):
            raise CheckError(f"无效副本输入：{name}")
        for item in snapshot_files(root, path):
            rel = item.relative_to(root)
            destination = target / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = item.read_bytes()
            destination.write_bytes(data)
            shutil.copymode(item, destination)
            manifests[str(rel)] = hashlib.sha256(data).hexdigest()
    if not manifests:
        raise CheckError("隔离副本为空")
    save(output, "snapshot", manifests)
    return target


def argv(options, key, substitutions=None):
    """展开配置 argv 中的精确占位符，不启用 shell 插值。

    Args:
        options: 当前检查器的配置项，使用其声明的默认值补齐可选项。
        key: 配置中保存命令参数列表的字段名。
        substitutions: 额外占位符到替换值的映射，仅替换完整参数。
    """
    value = options.get(key)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(a, str) or not a for a in value)
    ):
        raise CheckError(f"{key} 必须为非空 argv 列表")
    mapping = {"{python}": sys.executable, **(substitutions or {})}
    return [mapping.get(a, a) for a in value]


def clean_python_env(root):
    """构造隔离 Python 路径，避免从宿主工程导入未变异源码。

    Args:
        root: 工程根目录，调用方应传入已解析的绝对路径。
    """
    paths = [str(root), str(root / "src")]
    # 只继承检测工具路径，不把原项目源码加入副本的 Python 导入路径。
    tools_root = Path(__file__).resolve().parents[2] / ".tools"
    tool_paths = [str(tools_root / "node_modules/.bin"), str(tools_root)]
    search_path = os.pathsep.join(
        [
            str(Path(sys.executable).parent),
            os.environ.get("PATH", os.defpath),
            *tool_paths,
        ]
    )
    return [
        "env",
        "PYTHONPATH=" + os.pathsep.join(paths),
        "PATH=" + search_path,
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
    ]
