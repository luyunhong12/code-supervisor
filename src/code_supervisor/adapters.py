"""高级检查注册、配置校验和状态调度，不将未执行检查当作通过。"""

import importlib
import math

# 模块、函数、语言、默认模式、是否执行项目代码或网络请求。
REGISTRY = {
    "parameter-docs": ("parameter_docs", "parameter_docs", None, "quick", False),
    "pyright": ("audit", "pyright", "python", "full", False),
    "dependencies": ("audit", "dependencies", None, "full", False),
    "security": ("audit", "security", "python", "full", False),
    "secrets": ("audit", "secrets", None, "full", False),
    "vulnerabilities": ("audit", "vulnerabilities", None, "full", True),
    "crapper": ("quality", "crapper", "python", "full", True),
    "dryer": ("quality", "dryer", "python", "full", False),
    "mutator": ("quality", "mutator", "python", "deep", True),
    "doxygen": ("native", "doxygen", "cpp", "full", False),
    "cpp-build": ("native", "cpp_build", "cpp", "full", True),
    "clang-tidy": ("native", "clang_tidy", "cpp", "full", True),
    "cpp-coverage": ("native", "cpp_coverage", "cpp", "full", True),
    "cpp-sanitizers": ("native", "sanitizers", "cpp", "deep", True),
    "cpp-thread": ("native", "sanitizers", "cpp", "deep", True),
    "cpp-complexity": ("native", "cpp_complexity", "cpp", "full", False),
    "cpp-duplicates": ("native", "cpp_duplicates", "cpp", "full", False),
    "cpp-mutation": ("native", "cpp_mutation", "cpp", "deep", True),
    "acceptance": ("acceptance", "acceptance", None, "full", True),
}
COMMON = {"profile", "timeout", "files"}
NATIVE = {"inputs", "cmake_source", "configure_args", "jobs"}
OPTIONS = {
    "parameter-docs": {"paths", "documentation"},
    "pyright": {"config"},
    "dependencies": {"forbidden", "include_forbidden", "module_roots"},
    "security": set(),
    "secrets": {"paths", "max_bytes"},
    "vulnerabilities": {"requirements"},
    "crapper": {"inputs", "pytest_args", "threshold"},
    "dryer": {"threshold", "min_lines", "min_nodes"},
    "mutator": {"inputs", "pytest_args", "max_mutants", "mutant_timeout"},
    "doxygen": {"executable"},
    "cpp-build": NATIVE,
    "clang-tidy": NATIVE,
    "cpp-coverage": NATIVE | {"minimum"},
    "cpp-sanitizers": NATIVE | {"kind"},
    "cpp-thread": NATIVE,
    "cpp-complexity": {"threshold"},
    "cpp-duplicates": {"min_lines", "min_tokens"},
    "cpp-mutation": NATIVE | {"max_mutants"},
    "acceptance": {"inputs", "argv", "report", "limits"},
}


def validate_settings(settings):
    """校验高级检查参数，拒绝未知字段、错写模式和非有限阈值。"""
    if not isinstance(settings, dict) or set(settings) - set(REGISTRY):
        raise ValueError("settings 含未知高级检查")
    for name, options in settings.items():
        if not isinstance(options, dict) or set(options) - (COMMON | OPTIONS[name]):
            raise ValueError(f"{name} 含未知设置项")
        if "documentation" in options:
            documentation = options["documentation"]
            if not isinstance(documentation, dict) or not all(
                isinstance(key, str) and key and isinstance(value, str) and value
                for key, value in documentation.items()
            ):
                raise ValueError(
                    "documentation必须为配置路径到Markdown路径的非空字符串映射"
                )
        if options.get("profile", "full") not in {"quick", "full", "deep"}:
            raise ValueError(f"{name} profile 无效")
        for key in (
            "timeout",
            "threshold",
            "minimum",
            "min_lines",
            "min_nodes",
            "min_tokens",
            "max_mutants",
            "mutant_timeout",
            "jobs",
            "max_bytes",
        ):
            if key not in options:
                continue
            value = options[key]
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name}.{key} 必须为有限正数")
        for key in (
            "jobs",
            "max_mutants",
            "min_lines",
            "min_nodes",
            "min_tokens",
            "max_bytes",
        ):
            if key in options and type(options[key]) is not int:
                raise ValueError(f"{name}.{key} 必须为整数")
        if name == "dryer" and options.get("threshold", 0.8) > 1:
            raise ValueError("dryer.threshold 不得超过1")
        if options.get("minimum", 80) > 100:
            raise ValueError("覆盖率门槛不得超过100")
        for key in (
            "files",
            "inputs",
            "pytest_args",
            "paths",
            "configure_args",
            "argv",
            "module_roots",
        ):
            if key in options and (
                not isinstance(options[key], list)
                or any(not isinstance(v, str) or not v for v in options[key])
            ):
                raise ValueError(f"{name}.{key} 必须为字符串数组")
        for key in ("forbidden", "include_forbidden"):
            if key in options and (
                not isinstance(options[key], list)
                or any(
                    not isinstance(r, dict)
                    or set(r) != {"from", "to"}
                    or any(not isinstance(v, str) or not v for v in r.values())
                    for r in options[key]
                )
            ):
                raise ValueError(f"{name}.{key} 规则必须包含 from/to 非空字符串")
        if "limits" in options and (
            not isinstance(options["limits"], dict)
            or any(
                type(v) not in {int, float} or not math.isfinite(v)
                for v in options["limits"].values()
            )
        ):
            raise ValueError("limits 必须为有限数值映射")


def advanced_checks(root, cfg, files, output, profile, enabled):
    """按配置执行高级适配器，保留每项原始证据和明确失败状态。"""
    order = {"quick": 0, "full": 1, "deep": 2}
    results = []
    for name in cfg["checks"]:
        if name not in REGISTRY:
            continue
        module, function, language, default, executes = REGISTRY[name]
        options = dict(cfg.get("settings", {}).get(name, {}))
        selected = order[options.get("profile", default)] <= order[profile]
        if not selected:
            result = dict(status="not-run", reason="不属于本次模式")
        elif language and language not in files.values():
            result = dict(status="not-applicable", reason="范围内无适用语言源码")
        elif executes and not enabled:
            result = dict(
                status="not-run", reason="需 --run-commands 执行隔离测试/构建或漏洞查询"
            )
        else:
            folder = output / name
            folder.mkdir()
            if name == "cpp-thread":
                options["kind"] = "thread"
            try:
                callback = getattr(
                    importlib.import_module("code_supervisor." + module), function
                )
                result = callback(root, files, options, folder)
            except Exception as exc:
                result = dict(status="error", reason=f"{type(exc).__name__}: {exc}")
        results.append(
            dict(result, id=name, selected=selected, configured_options=options)
        )
    return results
