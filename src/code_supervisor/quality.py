"""原版 crapper/dryer/mutator 的专用适配及隔离覆盖率测量。"""

import ast
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .checks import finding
from .tasks import (
    CheckError,
    clean_python_env,
    run,
    save,
    selected_files,
    snapshot,
)


def setup_parsers():
    """使用已安装的语言缓存；缺失时由原工具报错，不自动下载源码。"""
    from tree_sitter_language_pack import configure, PackConfig

    cache = Path(__file__).resolve().parents[2] / ".tools/parsers"
    if cache.is_dir():
        configure(PackConfig(cache_dir=str(cache)))


def python_sources(root, files, options):
    """确认原工具支持的 .py 范围，并先用 AST 拒绝语法错误。

    Args:
        root: 工程根目录，调用方应传入已解析的绝对路径。
        files: 本次扫描得到的相对源码路径到语言的映射。
        options: 当前检查器的配置项，使用其声明的默认值补齐可选项。
    """
    selected = selected_files(root, files, options, "python")
    for name in selected:
        if not name.endswith(".py"):
            raise CheckError(f"原 ub 工具不支持无后缀入口：{name}；请显式选定 .py 范围")
        ast.parse((root / name).read_text())
    return selected


def measure(root, files, options, output):
    """在新副本运行真实 pytest 并生成覆盖率；拒绝旧报告和未导入文件。

    仅支持 pytest argv 参数列表，测试失败或选定源码没有执行记录时抛错。
    coverage 的输出绝对路径必须位于隔离副本，不接受安装目录中的同名模块。

    Args:
        root: 工程根目录，调用方应传入已解析的绝对路径。
        files: 本次扫描得到的相对源码路径到语言的映射。
        options: 当前检查器的配置项，使用其声明的默认值补齐可选项。
        output: 本次检查的独立输出目录，调用前应已创建。
    """
    names = python_sources(root, files, options)
    work = snapshot(root, output, options)
    for name in names:
        if not (work / name).is_file():
            raise CheckError(f"inputs 未包含选定源码：{name}")
    arguments = options.get("pytest_args")
    if (
        not isinstance(arguments, list)
        or not arguments
        or any(not isinstance(a, str) for a in arguments)
    ):
        raise CheckError('须设置 pytest_args，例如 ["tests", "-q"]')
    config = work / "coverage-supervisor.ini"
    config.write_text("[run]\nbranch = True\nrelative_files = False\n")
    command = clean_python_env(work) + [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--rcfile",
        str(config),
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        *arguments,
    ]
    run(command, work, output, "coverage-test", options.get("timeout", 120))
    path = output / "coverage.json"
    run(
        [
            sys.executable,
            "-m",
            "coverage",
            "json",
            "--rcfile",
            str(config),
            "-o",
            str(path),
        ],
        work,
        output,
        "coverage-export",
    )
    data = json.loads(path.read_text())
    normalized = {}
    for name, info in data["files"].items():
        full = (work / name).resolve()
        if full.is_relative_to(work):
            normalized[full.relative_to(work).as_posix()] = info
    missing = [name for name in names if name not in normalized]
    if missing:
        raise CheckError(f"测试未执行副本源码：{missing}")
    return work, names, normalized


def crapper(root, files, options, output):
    """用原版函数提取与 CRAP 公式，匹配本轮真实行/分支覆盖率。

    Args:
        root: 工程根目录，调用方应传入已解析的绝对路径。
        files: 本次扫描得到的相对源码路径到语言的映射。
        options: 当前检查器的配置项，使用其声明的默认值补齐可选项。
        output: 本次检查的独立输出目录，调用前应已创建。
    """
    setup_parsers()
    from crapper.analyze import analyze_files
    from crapper.coverage import CoverageBundle, FileCoverage

    work, names, coverage = measure(root, files, options, output)
    bundle = CoverageBundle()
    for name in names:
        data = coverage[name]
        entry = FileCoverage()
        executed = set(data["executed_lines"])
        for line in executed | set(data["missing_lines"]):
            entry[line] = (int(line in executed), 1)
        for key, hit in (("executed_branches", 1), ("missing_branches", 0)):
            for start, _ in data.get(key, []):
                covered, total = entry.branches.get(start, (0, 0))
                entry.branches[start] = covered + hit, total + 1
        bundle.lcov[name] = entry
    entries = analyze_files([work / n for n in names], work, bundle)
    if not entries:
        raise CheckError("crapper 未识别任何函数，不能报告通过")
    if any(e.crap is None or e.coverage is None for e in entries):
        raise CheckError("crapper 缺少可靠分数或覆盖率，不能生成数值结论")
    rows = [asdict(e) for e in entries]
    issues = [
        finding(
            e.path,
            1,
            "CRAP",
            f"{e.namespace}.{e.name}: CRAP={e.crap:.3f}, CC={e.complexity}, coverage={e.coverage:.2f}%",
        )
        for e in entries
        if e.crap >= options.get("threshold", 10)
    ]
    return dict(
        status="fail" if issues else "pass",
        findings=issues,
        evidence=save(output, "crapper", rows),
        functions=len(entries),
        scope="原版 crapper + 本轮隔离 pytest 覆盖；按实际选定文件，不覆盖 C++",
    )


def dryer(root, files, options, output):
    """读取原版结构指纹候选，不使用 dryer 的退出0判断无重复。

    Args:
        root: 工程根目录，调用方应传入已解析的绝对路径。
        files: 本次扫描得到的相对源码路径到语言的映射。
        options: 当前检查器的配置项，使用其声明的默认值补齐可选项。
        output: 本次检查的独立输出目录，调用前应已创建。
    """
    setup_parsers()
    from dryer.scan import scan_files, find_duplicates

    names = python_sources(root, files, options)
    entries, warnings = scan_files(
        [root / n for n in names],
        root,
        options.get("min_lines", 4),
        options.get("min_nodes", 20),
    )
    if warnings:
        raise CheckError("; ".join(warnings))
    pairs = find_duplicates(entries, options.get("threshold", 0.8))
    issues = [
        finding(
            p.left.file,
            p.left.start_line,
            "DUPLICATE",
            f"与 {p.right.file}:{p.right.start_line} 相似度 {p.score:.3f}；需判断业务语义",
        )
        for p in pairs
    ]
    return dict(
        status="fail" if issues else "pass",
        findings=issues,
        evidence=save(output, "dryer", [asdict(p) for p in pairs]),
        candidates_compared=len(entries),
        scope="原版 dryer；低于规模门槛的函数不会比较，0候选不表示不存在重复",
    )


def mutator(root, files, options, output):
    """使用原版变异位置生成器，在隔离副本逐个变异并执行实际测试。

    不把超时或基础设施错误算作杀死变异；语法无效项单列；超出预算或零执行不通过。
    每次测试启动新的解释器，测试前清除缓存；源码在 finally 中恢复。

    Args:
        root: 工程根目录，调用方应传入已解析的绝对路径。
        files: 本次扫描得到的相对源码路径到语言的映射。
        options: 当前检查器的配置项，使用其声明的默认值补齐可选项。
        output: 本次检查的独立输出目录，调用前应已创建。
    """
    setup_parsers()
    from mutator.functions import sites_in_file
    from coverage.parser import PythonParser
    from .process import execute

    work, names, coverage = measure(root, files, options, output)
    command = clean_python_env(work) + [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        *options["pytest_args"],
    ]
    outcomes = []
    budget = options.get("max_mutants", 100)
    executed = 0
    for name in names:
        path = work / name
        original = path.read_bytes()
        sites = sites_in_file(original.decode(), path, work, name)
        # coverage 将多行表达式归到语句首行；用同一映射匹配变异位置。
        line_parser = PythonParser(text=original.decode(), filename=str(path))
        line_parser.parse_source()
        covered_lines = set(coverage[name]["executed_lines"])
        for site in sites:
            record = dict(
                file=name,
                line=site.line,
                original=site.original,
                replacement=site.mutant,
                mutation_id=site.mutation_id,
            )
            if not (line_parser.translate_lines({site.line}) & covered_lines):
                record["outcome"] = "uncovered"
            elif executed >= budget:
                record["outcome"] = "budget-exhausted"
            else:
                mutated = (
                    original[: site.start] + site.mutant.encode() + original[site.end :]
                )
                try:
                    ast.parse(mutated)
                except SyntaxError:
                    record["outcome"] = "invalid"
                else:
                    try:
                        path.write_bytes(mutated)
                        result = execute(
                            command,
                            work,
                            output / f"mutant-{executed}.log",
                            options.get("mutant_timeout", 30),
                            finding_codes=[1],
                        )
                        record["outcome"] = {
                            "pass": "survived",
                            "fail": "killed",
                            "error": "error",
                        }[result["status"]]
                        executed += 1
                    finally:
                        path.write_bytes(original)
            outcomes.append(record)
            save(output, "mutator", outcomes)
    issues = [
        finding(r["file"], r["line"], "MUTATION", r["outcome"])
        for r in outcomes
        if r["outcome"] in {"survived", "uncovered"}
    ]
    incomplete = not executed or any(
        r["outcome"] in {"budget-exhausted", "error"} for r in outcomes
    )
    return dict(
        status="error" if incomplete else "fail" if issues else "pass",
        findings=issues,
        executed=executed,
        evidence=save(output, "mutator", outcomes),
        reason="无已执行变异或仍有预算/执行错误" if incomplete else "",
        scope="原版 mutator 位置和替换规则；独立执行器采用更严格超时/错误分类，等价变异需审查",
    )
