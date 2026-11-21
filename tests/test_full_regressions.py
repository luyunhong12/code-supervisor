"""全项目变异检查发现的协议与边界回归。"""

import pytest


def test_cli_only_configuration_and_empty_scope(tmp_path, monkeypatch):
    """纯配置工程正常执行，空范围不会通过命令行门禁。

    Args:
        tmp_path: 独立配置工程。
        monkeypatch: 命令行参数替换器。
    """
    from test_cli_contracts import invoke

    p = tmp_path / "supervisor.toml"
    p.write_text(
        'version=1\nchecks=["parameter-docs"]\n[settings.parameter-docs]\npaths=["a.xml"]\n'
    )
    (tmp_path / "a.xml").write_text("<!-- 配置。 --><a/>")
    assert invoke(monkeypatch, "check", tmp_path) == 0
    p.write_text(
        'version=1\nchecks=["parameter-docs"]\n[settings.parameter-docs]\npaths=[]\n'
    )
    assert invoke(monkeypatch, "check", tmp_path) == 2
    p.write_text('version=1\nchecks=["python-docs"]\n')
    assert invoke(monkeypatch, "check", tmp_path) == 2


def test_carriage_rejects_empty_success_and_wrong_container():
    """总状态为真也不能掩盖空工况，非空列表必须按协议错误拒绝。"""
    from test_scripts_contracts import script

    convert = script("carriage_suite.py")["convert_summary"]
    for results in [{}, [{"passed": True}]]:
        with pytest.raises(ValueError):
            convert(dict(complete=True, passed=True, results=results))


def test_prepare_refuses_existing_empty_output(tmp_path, monkeypatch):
    """即使输出目录为空也不得把它当作新验收目录。

    Args:
        tmp_path: 输入输出目录。
        monkeypatch: 命令行参数替换器。
    """
    from test_scripts_contracts import script

    root = tmp_path / "source"
    for name in ["src", "tools", "model", "docs"]:
        (root / name).mkdir(parents=True)
    for name in ["pyproject.toml", "pytest.ini"]:
        (root / name).write_text("")
    output = tmp_path / "existing"
    output.mkdir()
    monkeypatch.setattr("sys.argv", ["prepare", str(root), str(output)])
    with pytest.raises(FileExistsError):
        script("prepare_carriage.py")["main"]()
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("checks", [{}, ["a"], {"ok": 1}, {"ok": "true"}])
def test_invalid_acceptance_checks_with_valid_metrics(tmp_path, monkeypatch, checks):
    """有效指标不能掩盖无效或空的业务判据集合。

    Args:
        tmp_path: 验收副本目录。
        monkeypatch: 外部执行替换器。
        checks: 无效判据容器。
    """
    from code_supervisor import acceptance as module
    from code_supervisor.tasks import CheckError
    from test_tool_contracts import install_runner

    def snapshot(*args):
        """返回准备好的独立副本。

        Args:
            args: 副本创建参数。
        """
        return tmp_path

    monkeypatch.setattr(module, "snapshot", snapshot)
    install_runner(
        monkeypatch,
        module,
        tmp_path,
        {"result.json": dict(checks=checks, metrics={"seconds": 1})},
    )
    with pytest.raises(CheckError, match="布尔映射"):
        module.acceptance(
            tmp_path,
            {},
            dict(report="result.json", argv=["tool"], limits={"seconds": 2}),
            tmp_path,
        )


def test_nested_package_dependency_names(tmp_path):
    """嵌套包和普通模块的相对导入均使用完整包路径。

    Args:
        tmp_path: 独立源码根目录。
    """
    import json
    from pathlib import Path
    from code_supervisor.audit import dependencies

    (tmp_path / "core/inner").mkdir(parents=True)
    (tmp_path / "core/inner/__init__.py").write_text("from . import api\n")
    (tmp_path / "core/inner/api.py").write_text("from . import sibling\n")
    files = {"core/inner/__init__.py": "python", "core/inner/api.py": "python"}
    result = dependencies(
        tmp_path,
        files,
        {"forbidden": [{"from": "core.inner", "to": "core.inner.sibling"}]},
        tmp_path,
    )
    assert result["status"] == "fail"
    assert result["findings"] == [
        dict(
            file="core/inner/api.py",
            line=1,
            rule="DEPENDENCY",
            message="core.inner.api 不允许依赖 core.inner.sibling",
        )
    ]
    rows = json.loads(Path(result["evidence"]).read_text())
    assert rows[0]["source"] == "core.inner" and rows[0]["target"] == "core.inner"


def test_black_default_normalization_and_magic_comma(tmp_path):
    """默认统一字符串引号并保留魔法逗号产生的多行排版。

    Args:
        tmp_path: 源码目录。
    """
    from code_supervisor.checks import black_check

    source = tmp_path / "a.py"
    source.write_text("x = 'hello'\n")
    assert black_check(tmp_path, ["a.py"])["status"] == "fail"
    source.write_text("x = [\n    1,\n    2,\n]\n")
    assert black_check(tmp_path, ["a.py"])["status"] == "pass"
    (tmp_path / "pyproject.toml").write_text(
        "[tool.black]\nskip-magic-trailing-comma=true\n"
    )
    assert black_check(tmp_path, ["a.py"])["status"] == "fail"


def test_black_requests_ast_safety_check(tmp_path, monkeypatch):
    """格式检查必须启用 Black 的 AST 等价校验，不走跳过校验的快速模式。

    Args:
        tmp_path: 源码目录。
        monkeypatch: 替换 Black 公共调用边界。
    """
    import black
    from code_supervisor.checks import black_check

    (tmp_path / "a.py").write_text("x=1")

    def format_contents(source, fast, mode):
        """验证检测器要求的安全模式。

        Args:
            source: 原始源码。
            fast: 是否跳过 AST 安全校验。
            mode: 格式规范。
        """
        assert fast is False
        assert source == "x=1"
        raise black.NothingChanged

    monkeypatch.setattr(black, "format_file_contents", format_contents)
    assert black_check(tmp_path, ["a.py"])["status"] == "pass"


def test_black_diagnostics_use_one_based_lines(tmp_path):
    """格式和语法诊断都输出有效的一基文件行号。

    Args:
        tmp_path: 源码目录。
    """
    from code_supervisor.checks import black_check

    for source, rule in [("x=1", "BLACK-FORMAT"), ("def f(", "BLACK-PARSE")]:
        (tmp_path / "a.py").write_text(source)
        issue = black_check(tmp_path, ["a.py"])["findings"][0]
        assert issue["file"] == "a.py" and issue["line"] == 1 and issue["rule"] == rule


def test_command_skip_reasons(tmp_path):
    """不属于模式与未授权执行使用不同的可操作提示。

    Args:
        tmp_path: 检查目录。
    """
    from code_supervisor.cli import command_checks

    cfg = {
        "commands": [
            dict(
                id="later", argv=["tool"], profile="deep", timeout=1, finding_codes=[1]
            )
        ]
    }
    first = command_checks(tmp_path, cfg, "quick", False, tmp_path)[0]
    second = command_checks(tmp_path, cfg, "deep", False, tmp_path)[0]
    assert first["selected"] is False and first["reason"] == "不属于本次模式"
    assert (
        second["selected"] is True
        and second["reason"] == "配置命令需要 --run-commands 才会执行"
    )


def test_report_outputs_preserve_chinese_and_locations(tmp_path):
    """JSON、SARIF 与文本均保留可读中文及定位信息。

    Args:
        tmp_path: 报告输出目录。
    """
    import json
    from code_supervisor.cli import write_report

    report = dict(
        root=str(tmp_path),
        profile="full",
        files={"a.py": "python"},
        exit_code=2,
        version="test",
        results=[
            dict(
                id="docs",
                status="error",
                reason="无法解析",
                scope="中文范围",
                findings=[dict(file="a.py", line=4, rule="X", message="缺少说明")],
                unparsed_files=["x.cpp"],
            )
        ],
    )
    write_report(tmp_path, report)
    raw = (tmp_path / "report.json").read_text()
    assert "无法解析" in raw and json.loads(raw) == report
    assert "缺少说明" in (tmp_path / "report.sarif").read_text()
    text = (tmp_path / "report.txt").read_text()
    assert "a.py:4 [X] 缺少说明" in text and "无法完整解析：x.cpp" in text
    assert "中文范围" in text and text.endswith("\n")


def test_report_directory_collision_does_not_overwrite(tmp_path, monkeypatch):
    """即使运行标识碰撞也必须保留已有报告。

    Args:
        tmp_path: 独立工程与输出目录。
        monkeypatch: 固定时钟与运行标识。
    """
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from code_supervisor import cli
    from test_cli_contracts import invoke

    def now(zone):
        """返回固定的运行时间。

        Args:
            zone: 请求的时区。
        """
        return datetime(2026, 11, 19, tzinfo=timezone.utc)

    def identifier():
        """返回会重复的运行标识以验证碰撞处理。"""
        return SimpleNamespace(hex="abcdef12" * 4)

    root = tmp_path / "project"
    root.mkdir()
    (root / "a.py").write_text('"""模块。"""')
    (root / "supervisor.toml").write_text('version=1\nchecks=["python-docs"]')
    monkeypatch.setattr(cli, "datetime", SimpleNamespace(now=now))
    monkeypatch.setattr(cli.uuid, "uuid4", identifier)
    out = tmp_path / "output"
    assert invoke(monkeypatch, "check", root, "--output", out) == 0
    report = next(out.glob("*/report.json"))
    original = report.read_bytes()
    assert invoke(monkeypatch, "check", root, "--output", out) == 2
    assert report.read_bytes() == original


def test_cli_policy_removed_during_check_invalidates_snapshot(tmp_path, monkeypatch):
    """规范文件在检查中消失时不能声称一致快照或检查通过。

    Args:
        tmp_path: 独立工程目录。
        monkeypatch: 在检查边界模拟外部删除。
    """
    import json
    from code_supervisor import cli
    from test_cli_contracts import invoke

    (tmp_path / "a.py").write_text('"""模块。"""')
    (tmp_path / "rules.md").write_text("规范")
    (tmp_path / "supervisor.toml").write_text(
        'version=1\nchecks=["python-docs"]\npolicy=["rules.md"]'
    )

    def remove_policy(root, cfg, files, output):
        """模拟检查期间的外部规范修改。

        Args:
            root: 工程目录。
            cfg: 当前配置。
            files: 已发现的文件。
            output: 证据目录。
        """
        (root / "rules.md").unlink()
        return [dict(id="python-docs", status="pass")]

    monkeypatch.setattr(cli, "builtin_checks", remove_policy)
    assert invoke(monkeypatch, "check", tmp_path) == 2
    report = json.loads(
        next((tmp_path / ".generated/supervisor").glob("*/report.json")).read_text()
    )
    assert report["source_unchanged"] is False
    assert report["results"][-1]["id"] == "snapshot"


def test_cli_requires_subcommand(monkeypatch):
    """缺少子命令必须给出参数错误，不能进入执行逻辑。

    Args:
        monkeypatch: 命令行参数替换器。
    """
    from test_cli_contracts import invoke

    with pytest.raises(SystemExit) as error:
        invoke(monkeypatch)
    assert error.value.code == 2


def test_explicit_generated_source_is_excluded(tmp_path):
    """显式指定生成目录中的文件也不得绕过默认排除规则。

    Args:
        tmp_path: 工程目录。
    """
    from code_supervisor.config import discover

    (tmp_path / "build").mkdir()
    (tmp_path / "build/a.py").write_text("x=1")
    assert discover(tmp_path, dict(source=["build/a.py"], exclude=[])) == {}
    assert discover(tmp_path, dict(source=["build"], exclude=[])) == {}


def test_cpp_variable_comment_does_not_document_embedded_type():
    """带对象声明的外层注释不自动关联到内嵌类型定义。"""
    from tree_sitter import Language, Parser
    import tree_sitter_cpp
    from code_supervisor.cpp import preceding, targets

    source = "/** 对象说明。 */\nstruct S { int x; } instance;".encode()
    tree = Parser(Language(tree_sitter_cpp.language())).parse(source)
    node = list(targets(tree))[0]
    assert preceding(node, source) == ""


def test_mutation_coverage_does_not_borrow_try_anchor(tmp_path, monkeypatch):
    """try 被执行不代表 except 内变异被覆盖，仍须核对实际语句行号。

    Args:
        tmp_path: 隔离源码目录。
        monkeypatch: 替换基线覆盖事实及测试进程。
    """
    import json
    from code_supervisor import quality, process

    source = b"def f():\n    try:\n        return 1\n    except ValueError:\n        return 0\n"
    path = tmp_path / "a.py"
    path.write_bytes(source)

    def measure(*args):
        """返回只执行正常路径的覆盖事实。

        Args:
            args: 覆盖测量参数。
        """
        return tmp_path, ["a.py"], {"a.py": {"executed_lines": [1, 2, 3]}}

    def execute(*args, **kwargs):
        """只允许执行正常返回语句的变异。

        Args:
            args: 测试执行参数。
            kwargs: 退出码分类。
        """
        assert path.read_bytes() == source.replace(b"return 1", b"return 0")
        return {"status": "fail"}

    monkeypatch.setattr(quality, "measure", measure)
    monkeypatch.setattr(process, "execute", execute)
    result = quality.mutator(
        tmp_path, {"a.py": "python"}, {"pytest_args": ["tests"]}, tmp_path
    )
    assert result["status"] == "fail" and result["executed"] == 1
    records = json.loads((tmp_path / "mutator.json").read_text())
    assert [row["outcome"] for row in records] == ["killed", "uncovered"]
    assert path.read_bytes() == source


def test_cpp_already_terminated_registration_stays_unchanged():
    """已有分号的插件注册不应再补分号。"""
    from code_supervisor.cpp import cpp_parameter_source

    source = b'GZ_ADD_PLUGIN(A,B);\nGZ_ADD_PLUGIN_ALIAS(A,"alias");\n'
    assert cpp_parameter_source(source) == source


@pytest.mark.parametrize(
    "source",
    [
        "/** 说明。 */",
        "/** @file a.hh */",
        "/** @brief 中文。 */",
        "// 中文说明。",
        "/** @file a.hh @brief English. */",
        '/** 占位说明。 */\nconst char* text="@file fake @brief 中文";',
    ],
)
def test_cpp_file_contract_not_borrowed_from_other_text(tmp_path, source):
    """文件说明需自身满足语法、标签与中文要求，字符串不能补足缺项。

    Args:
        tmp_path: 源码目录。
        source: 缺少完整文件说明的源码。
    """
    from code_supervisor.cpp import cpp_docs

    (tmp_path / "a.hh").write_text(source)
    result = cpp_docs(tmp_path, ["a.hh"])
    assert result["status"] == "fail"
    assert any(x["rule"] == "CPP-FILE" and x["line"] == 1 for x in result["findings"])


@pytest.mark.parametrize("operator", ["%", "<<", ">>", "&", "|", "^", "<=", ">="])
def test_cpp_mutation_skips_unsupported_operators(operator):
    """有限算子后端对未支持运算符保持明确的空候选结果。

    Args:
        operator: 尚未支持的合法 C++ 二元运算符。
    """
    from code_supervisor.native import mutation_sites

    assert (
        mutation_sites(("int f(int x){ return x " + operator + " 2; }").encode()) == []
    )


def test_cpp_function_documentation_messages_and_lines(tmp_path):
    """缺中文与缺 brief 分别报告，并保留声明的真实一基行号。

    Args:
        tmp_path: 源码目录。
    """
    from code_supervisor.cpp import cpp_docs

    source = "/** @file a.hh\n * @brief 文件。\n */\n/** @brief English. */\nint f();\n/** 中文但没有标签。 */\nint g();\n"
    (tmp_path / "a.hh").write_text(source)
    result = cpp_docs(tmp_path, ["a.hh"])
    assert [(x["rule"], x["line"]) for x in result["findings"]] == [
        ("CPP-DOC", 5),
        ("CPP-BRIEF", 7),
    ]
    assert result["status"] == "fail" and result["definitions"] == 2


def test_cpp_missing_execution_count_is_not_covered(tmp_path, monkeypatch):
    """覆盖数据缺少执行次数时不能凭空计入已覆盖行。

    Args:
        tmp_path: 构建和证据目录。
        monkeypatch: 工具替换器。
    """
    from code_supervisor import native
    from test_tool_contracts import native_workspace, install_runner

    native_workspace(monkeypatch, tmp_path)
    install_runner(
        monkeypatch,
        native,
        tmp_path,
        {
            "coverage-tests.xml": "<testsuite><testcase/></testsuite>",
            "gcovr.json": {"files": [dict(file="a.cc", lines=[{"count": 1}, {}])]},
        },
    )
    result = native.cpp_coverage(tmp_path, {"a.cc": "cpp"}, {"minimum": 50}, tmp_path)
    assert result["coverage"] == 50 and result["status"] == "pass"


def test_cpp_malformed_root_remains_parseable_input():
    """缺失分号作为根节点时适配器不能解引用不存在的父节点。"""
    from code_supervisor.cpp import cpp_parameter_source

    assert cpp_parameter_source(b"*.py") == b"*.py"


def test_process_elapsed_and_json_readability(tmp_path, monkeypatch):
    """耗时取时钟差值，证据保留可直接阅读的中文。

    Args:
        tmp_path: 日志和证据目录。
        monkeypatch: 替换单调时钟。
    """
    from code_supervisor import process, tasks

    times = iter([10.0, 10.25])
    monkeypatch.setattr(process.time, "monotonic", lambda: next(times))
    result = process.execute(
        ["/missing-supervisor-test-binary"], tmp_path, tmp_path / "log"
    )
    assert result["status"] == "error" and result["seconds"] == 0.25
    path = tasks.save(tmp_path, "evidence", {"message": "中文证据"})
    assert "中文证据" in __import__("pathlib").Path(path).read_text()


@pytest.mark.parametrize("inputs", [[], ["src"]])
def test_snapshot_wrong_input_container(tmp_path, inputs):
    """快照要求非空列表，元组不能绕过配置协议。

    Args:
        tmp_path: 源码和输出目录。
        inputs: 用于构造非列表配置的内容。
    """
    from code_supervisor.tasks import snapshot, CheckError

    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("pass")
    with pytest.raises(CheckError, match="须配置 inputs"):
        snapshot(tmp_path, tmp_path, {"inputs": tuple(inputs)})


def test_duplicate_report_missing_scan_count(tmp_path, monkeypatch):
    """缺少实际扫描文件数量的报告不能被解释为零重复。

    Args:
        tmp_path: 证据目录。
        monkeypatch: 替换工具运行。
    """
    from code_supervisor import native
    from code_supervisor.tasks import CheckError
    from test_tool_contracts import install_runner

    install_runner(
        monkeypatch,
        native,
        tmp_path,
        {"jscpd-report.json": dict(statistics=dict(total={}), duplicates=[])},
    )
    with pytest.raises(CheckError, match="没有扫描"):
        native.cpp_duplicates(tmp_path, {"a.cc": "cpp"}, {}, tmp_path)


@pytest.mark.parametrize("literal", [b'R"(value)"', b'u8"value"'])
def test_cpp_member_operator_adjacent_to_literal(literal):
    """重载成员指针运算符的字符串实参不与运算符区间重叠。

    Args:
        literal: 与运算符相邻的原始或带编码前缀的字符串。
    """
    from code_supervisor.cpp import cpp_parameter_source

    prefix = b"struct A {}; int operator->*(A, const char*); void f(){ A a; a"
    source = prefix + b"->*" + literal + b"; }"
    adapted = cpp_parameter_source(source)
    assert adapted == prefix + b".  " + literal + b"; }"
    assert len(adapted) == len(source)


def test_xml_settings_without_enabled_checker_cannot_pass(tmp_path, monkeypatch):
    """仅存在配置路径不能替代实际启用的参数检查器。

    Args:
        tmp_path: 只有 XML 的工程。
        monkeypatch: 命令行参数替换器。
    """
    from test_cli_contracts import invoke

    (tmp_path / "supervisor.toml").write_text(
        'version=1\nchecks=["python-docs"]\n[settings.parameter-docs]\npaths=["a.xml"]\n'
    )
    (tmp_path / "a.xml").write_text("<!-- 配置。 --><a/>")
    assert invoke(monkeypatch, "check", tmp_path) == 2
    assert not (tmp_path / ".generated").exists()


@pytest.mark.parametrize(
    "source",
    [b"asm(SYMBOL);", b"void f(){ asm(SYMBOL); }", b"class C { asm(SYMBOL); };"],
)
def test_cpp_asm_outside_declaration_tail_is_preserved(source):
    """仅适配声明尾部符号标签，不擦除独立 asm 或函数体中的解析问题。

    Args:
        source: 不属于受支持声明尾部的汇编语法。
    """
    from code_supervisor.cpp import cpp_parameter_source

    assert cpp_parameter_source(source) == source
