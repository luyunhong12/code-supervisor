"""创建车辆工程的独立验收副本；不改动原工程的源码和构建目录。"""

import argparse
import json
from pathlib import Path
import shutil
import tomllib

from code_supervisor.tasks import snapshot


CONFIG = """version = 1
name = "carriage-isolated"
source = ["src", "tools"]
checks = ["python-docs", "black", "ruff", "cpp-docs", "parameter-docs", "dryer", "cpp-complexity", "cpp-duplicates", "acceptance"]
policy = ["docs/0-0、代码规范（通用）.md", "docs/1-1、代码结构与拆分规则.md"]
[settings.acceptance]
inputs = ["src", "tools", "model", "supervisor_carriage.py", "supervisor-copy.json", "pyproject.toml", "pytest.ini"]
argv = ["{python}", "supervisor_carriage.py", "SUITE", "{report}"]
report = "acceptance-result.json"
timeout = 14400
"""


def main():
    """复制显式业务输入，生成复用现有验收的配置与本地 C++ 测试配置。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--suite", choices=("code", "baseline", "experimental"), default="code"
    )
    args = parser.parse_args()
    root, output = args.project.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    work = snapshot(
        root,
        output,
        dict(inputs=["src", "tools", "model", "docs", "pyproject.toml", "pytest.ini"]),
    )
    (work / "supervisor-copy.json").write_text(
        json.dumps(dict(origin=str(root), manifest=str(output / "snapshot.json")))
    )
    shutil.copyfile(
        Path(__file__).with_name("carriage_suite.py"), work / "supervisor_carriage.py"
    )
    config_paths = [
        p.relative_to(work).as_posix()
        for p in sorted((work / "src").glob("*/config"))
        if p.is_dir()
    ]
    parameter_rule = (
        "\n[settings.parameter-docs]\npaths = " + json.dumps(config_paths) + "\n"
    )
    parameter_config = root / "supervisor/parameters.toml"
    if parameter_config.is_file():
        settings = tomllib.loads(parameter_config.read_text()).get("settings", {})
        documentation = settings.get("parameter-docs", {}).get("documentation", {})
        parameter_rule += "\n[settings.parameter-docs.documentation]\n"
        for source, document in documentation.items():
            if not (work / document).is_file():
                raise ValueError(f"验收副本缺少参数说明：{document}")
            parameter_rule += json.dumps(source) + " = " + json.dumps(document) + "\n"
    python_files = sorted(
        p.relative_to(work).as_posix()
        for folder in ("src", "tools")
        for p in (work / folder).rglob("*.py")
    )
    dryer_rule = "\n[settings.dryer]\nfiles = " + json.dumps(python_files) + "\n"
    (work / "supervisor.toml").write_text(
        CONFIG.replace("SUITE", args.suite) + parameter_rule + dryer_rule
    )
    harness = work / "supervisor-native"
    harness.mkdir()
    (harness / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\nproject(CarriageBrakeAudit LANGUAGES CXX)\nset(CMAKE_CXX_STANDARD 17)\nenable_testing()\nadd_executable(brake ../src/carriage_control/test/test_brake_law.cc)\ntarget_include_directories(brake PRIVATE ../src/carriage_control/native)\nadd_test(NAME brake COMMAND brake)\n"
    )
    config = 'version = 1\nname = "carriage-brake"\nsource = ["src/carriage_control/native/brake_law.hh", "src/carriage_control/test/test_brake_law.cc"]\nchecks = ["cpp-build", "clang-tidy", "cpp-coverage", "cpp-sanitizers", "cpp-complexity", "cpp-mutation"]\n'
    for name in (
        "cpp-build",
        "clang-tidy",
        "cpp-coverage",
        "cpp-sanitizers",
        "cpp-mutation",
    ):
        config += (
            "\n[settings."
            + name
            + ']\ninputs = ["src/carriage_control/native/brake_law.hh", "src/carriage_control/test/test_brake_law.cc", "supervisor-native"]\ncmake_source = "supervisor-native"\n'
        )
        if name in ("cpp-coverage", "cpp-mutation"):
            config += 'files = ["src/carriage_control/native/brake_law.hh"]\n'
        if name == "cpp-mutation":
            config += "max_mutants = 200\n"
    (work / "supervisor-brake.toml").write_text(config)
    print(work)


if __name__ == "__main__":
    main()
