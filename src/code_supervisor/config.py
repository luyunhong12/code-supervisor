"""读取项目配置和扫描范围，拒绝越界路径与无效配置。"""

import fnmatch
import math
import re
import tomllib

from .adapters import REGISTRY, validate_settings

EXCLUDED = {
    ".git",
    ".venv",
    "venv",
    "build",
    "install",
    "log",
    ".generated",
    "__pycache__",
    "node_modules",
    ".tools",
    ".build",
    "target",
    "vendor",
}
CPP_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
CHECKS = {"python-docs", "black", "ruff", "cpp-docs"}
PROFILES = {"quick", "full", "deep"}


def inside(root, name):
    """解析工程内路径；越界路径抛出 ValueError，不要求目标已存在。"""
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"路径不在工程内：{name}")
    return path


def load(root, config_path):
    """读取并校验 TOML，返回配置；不执行配置中的命令。

    Args:
        root: 已解析的项目根目录。
        config_path: 配置文件路径，可以位于被检查工程之外。

    Returns:
        完成默认值补齐和命令结构校验的配置映射。

    Raises:
        ValueError: 配置缺项、类型无效、路径越界或检查名称未知。
        OSError: 配置文件无法读取。
    """
    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if cfg.get("version") != 1:
        raise ValueError("配置 version 必须为 1")
    unknown = set(cfg) - {
        "version",
        "name",
        "source",
        "exclude",
        "checks",
        "policy",
        "commands",
        "required",
        "settings",
    }
    if unknown:
        raise ValueError(f"未知配置项：{sorted(unknown)}")
    for key, default in (
        ("source", ["."]),
        ("exclude", []),
        ("checks", sorted(CHECKS)),
        ("policy", []),
    ):
        cfg.setdefault(key, default)
        if not isinstance(cfg[key], list) or not all(
            isinstance(s, str) and s for s in cfg[key]
        ):
            raise ValueError(f"{key} 必须为非空字符串组成的列表")
    if not cfg["source"] or not cfg["checks"]:
        raise ValueError("source 和 checks 不得为空")
    if set(cfg["checks"]) - (CHECKS | set(REGISTRY)):
        raise ValueError("checks 中含不支持的检查器")
    for name in cfg["source"] + cfg["policy"]:
        if not inside(root, name).exists():
            raise ValueError(f"配置路径不存在：{name}")
    commands = cfg.setdefault("commands", [])
    if not isinstance(commands, list):
        raise ValueError("commands 必须使用 [[commands]] 数组")
    ids = set()
    for item in commands:
        validate_command(item, ids)
    required = cfg.setdefault("required", {})
    if not isinstance(required, dict) or set(required) - PROFILES:
        raise ValueError("required 只支持 quick/full/deep")
    for names in required.values():
        if not isinstance(names, list) or any(
            not isinstance(n, str) or not n for n in names
        ):
            raise ValueError("required 各模式须为非空名称列表")
    validate_settings(cfg.setdefault("settings", {}))
    if len(cfg["checks"]) != len(set(cfg["checks"])):
        raise ValueError("checks 不得重复")
    if set(ids) & set(cfg["checks"]):
        raise ValueError("命令 id 不得与检查器重名")
    return cfg


def validate_command(item, ids):
    """校验一个显式外部检查命令；非法配置抛出 ValueError。"""
    if not isinstance(item, dict) or set(item) - {
        "id",
        "argv",
        "profile",
        "timeout",
        "finding_codes",
    }:
        raise ValueError("commands 含未知字段")
    name = item.get("id", "")
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[a-z][a-z0-9-]*", name)
        or name in ids
        or name in CHECKS
    ):
        raise ValueError(f"命令 id 无效或重复：{name}")
    ids.add(name)
    argv = item.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(a, str) and a and "\0" not in a for a in argv)
    ):
        raise ValueError(f"{name}: argv 必须是非空字符串数组")
    if item.get("profile", "full") not in PROFILES:
        raise ValueError(f"{name}: profile 无效")
    timeout = item.setdefault("timeout", 120)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (float, int))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError(f"{name}: timeout 必须为有限正秒数")
    codes = item.setdefault("finding_codes", [1])
    if not isinstance(codes, list) or any(
        type(c) is not int or c <= 0 or c > 255 for c in codes
    ):
        raise ValueError(f"{name}: finding_codes 必须为正退出码列表")


def discover(root, cfg):
    """发现范围内的 Python/C++ 文件，含未跟踪文件和 Python shebang。

    不遍历符号链接与默认生成目录；返回相对路径到语言的映射。
    路径不可读时传播 OSError，避免把扫描失败当作无问题。
    """
    found = {}
    for name in cfg["source"]:
        source = inside(root, name)
        candidates = [source] if source.is_file() else walk(source)
        for path in candidates:
            rel = path.relative_to(root)
            if path.is_symlink() or any(part in EXCLUDED for part in rel.parts):
                continue
            if any(fnmatch.fnmatch(rel.as_posix(), pat) for pat in cfg["exclude"]):
                continue
            if path.suffix in CPP_SUFFIXES:
                found[rel.as_posix()] = "cpp"
            elif path.suffix == ".py":
                found[rel.as_posix()] = "python"
            elif not path.suffix:
                with path.open("rb") as stream:
                    first = stream.readline(256)
                if first.startswith(b"#!") and b"python" in first:
                    found[rel.as_posix()] = "python"
    return dict(sorted(found.items()))


def walk(folder):
    """递归返回普通文件，提前剪去生成目录和符号链接。"""
    for path in sorted(folder.iterdir()):
        if path.is_symlink() or path.name in EXCLUDED:
            continue
        if path.is_dir():
            yield from walk(path)
        elif path.is_file():
            yield path
