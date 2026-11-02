"""隔离副本、证据文件和外部工具调用的公共边界。"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from .config import inside
from .process import execute


class CheckError(RuntimeError):
    """检查无法获得可靠证据时使用的错误。"""


def tool(name):
    """优先使用同一虚拟环境内的工具，随后查找 PATH 和独立工具目录。"""
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
    """运行命令并保存日志；非预期退出码抛错，不将工具失败解释为发现问题。"""
    log = output / f"{label}.log"
    result = execute(argv, root, log, timeout, finding_codes=())
    if result.get("returncode") not in accepted:
        raise CheckError(
            f'{label} 执行失败：{result.get("reason", result.get("returncode"))}；日志 {log}'
        )
    return log, result["returncode"]


def save(output, name, value):
    """写入单次运行的 JSON 证据，不覆盖业务文件。"""
    path = output / (name + ".json")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def selected_files(root, files, options, language):
    """选取适配器明确指定的文件，拒绝范围外或类型不符的路径。"""
    names = options.get("files", [f for f, lang in files.items() if lang == language])
    if not isinstance(names, list) or any(
        not isinstance(f, str) or files.get(f) != language for f in names
    ):
        raise CheckError("files 必须属于本次扫描范围且语言匹配")
    if not names:
        raise CheckError(f"未选定 {language} 源码")
    return names


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
        candidates = path.rglob("*") if path.is_dir() else [path]
        for item in candidates:
            if item.is_symlink():
                raise CheckError(f"副本输入含符号链接：{item}")
            if not item.is_file():
                continue
            rel = item.relative_to(root)
            if any(
                p
                in {
                    ".git",
                    ".venv",
                    "__pycache__",
                    ".pytest_cache",
                    ".generated",
                    "build",
                    "install",
                    "log",
                }
                for p in rel.parts
            ):
                continue
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
    """展开配置 argv 中的精确占位符，不启用 shell 插值。"""
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
    """构造隔离 Python 路径，避免从宿主工程导入未变异源码。"""
    paths = [str(root), str(root / "src")]
    return [
        "env",
        "PYTHONPATH=" + os.pathsep.join(paths),
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
    ]
