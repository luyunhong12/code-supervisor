"""外部检测器协议、阈值与失败边界；只模拟工具输出，不访问网络或设备。"""

import json
from pathlib import Path

import pytest

from code_supervisor import audit, native, acceptance as acceptance_module
from code_supervisor.tasks import CheckError


def install_runner(monkeypatch, module, output, payload, code=0):
    """安装可记录调用并生成协议文件的假外部进程。

    Args:
        monkeypatch: pytest 替换工具。
        module: 要替换外部运行边界的模块。
        output: 生成证据的目录。
        payload: 相对文件名到文本或 JSON 内容的映射。
        code: 模拟的退出码。
    """
    calls = []

    def run(*args, **kwargs):
        """模拟一次外部调用并保留实际参数。

        Args:
            args: 原始位置参数。
            kwargs: 原始关键字参数。
        """
        calls.append((args, kwargs))
        for name, value in payload.items():
            path = output / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value if isinstance(value, str) else json.dumps(value))
        log = output / "tool.log"
        if not log.exists():
            log.write_text("")
        if code not in kwargs.get("accepted", (0,)):
            raise CheckError(f"模拟工具退出码不被接受：{code}")
        return log, code

    def tool(name):
        """返回确定性的模拟可执行路径。

        Args:
            name: 工具名称。
        """
        return "/tool/" + name

    monkeypatch.setattr(module, "run", run)
    if hasattr(module, "tool"):
        monkeypatch.setattr(module, "tool", tool)
    return calls


@pytest.mark.parametrize(
    "count,diagnostics,expected",
    [
        (0, [], "error"),
        (1, [], "pass"),
        (
            1,
            [
                dict(
                    file="a.py",
                    range=dict(start=dict(line=0)),
                    message="类型错误",
                    severity="error",
                )
            ],
            "fail",
        ),
        (
            1,
            [
                dict(
                    file="a.py",
                    range=dict(start=dict(line=2)),
                    message="提示",
                    severity="information",
                )
            ],
            "pass",
        ),
    ],
)
def test_pyright_protocol(tmp_path, monkeypatch, count, diagnostics, expected):
    """零文件不能通过，信息提示不冒充错误，诊断行号转换为一基。

    Args:
        tmp_path: 证据目录。
        monkeypatch: 工具替换器。
        count: 工具报告的分析文件数。
        diagnostics: 工具返回的诊断集合。
        expected: 预期状态。
    """
    calls = install_runner(
        monkeypatch,
        audit,
        tmp_path,
        {
            "tool.log": {
                "summary": {"filesAnalyzed": count},
                "generalDiagnostics": diagnostics,
            }
        },
    )
    if expected == "error":
        with pytest.raises(CheckError, match="没有分析"):
            audit.pyright(tmp_path, {"a.py": "python"}, {}, tmp_path)
    else:
        result = audit.pyright(
            tmp_path, {"a.py": "python"}, {"config": "pyright.json"}, tmp_path
        )
        assert result["status"] == expected
        if expected == "fail":
            assert result["findings"] == [
                dict(file="a.py", line=1, rule="PYRIGHT", message="类型错误")
            ]
        assert calls[0][0][0] == [
            "/tool/pyright",
            "--outputjson",
            "--project",
            str(tmp_path / "pyright.json"),
            str(tmp_path / "a.py"),
        ]


@pytest.mark.parametrize("errors,expected", [([], "pass"), (["不可读"], "error")])
def test_bandit_errors(tmp_path, monkeypatch, errors, expected):
    """扫描错误不能被零诊断掩盖。

    Args:
        tmp_path: 证据目录。
        monkeypatch: 工具替换器。
        errors: Bandit 扫描错误。
        expected: 预期状态。
    """
    install_runner(
        monkeypatch, audit, tmp_path, {"bandit.json": dict(errors=errors, results=[])}
    )
    if expected == "error":
        with pytest.raises(CheckError):
            audit.security(tmp_path, {"a.py": "python"}, {}, tmp_path)
    else:
        assert (
            audit.security(tmp_path, {"a.py": "python"}, {}, tmp_path)["status"]
            == "pass"
        )


@pytest.mark.parametrize(
    "text,deps,expected",
    [
        ("# 清单\nfoo==1\n", [dict(name="foo", version="1", vulns=[])], "pass"),
        (
            "foo==1\n",
            [dict(name="foo", version="1", vulns=[dict(id="V-1", fix_versions=["2"])])],
            "fail",
        ),
        ("foo==1\n", [], "error"),
        ("foo==1\n", [dict(name="foo", version="1", skip_reason="网络错误")], "error"),
        ("", [], "error"),
        ("foo>=1", [], "error"),
        ("-e .", [], "error"),
    ],
)
def test_vulnerability_protocol(tmp_path, monkeypatch, text, deps, expected):
    """锁定清单、完整查询和漏洞诊断分开判断；不进行网络访问。

    Args:
        tmp_path: 清单和证据目录。
        monkeypatch: 外部工具替换器。
        text: 依赖清单内容。
        deps: 模拟查询结果。
        expected: 预期状态。
    """
    (tmp_path / "requirements.txt").write_text(text)
    calls = install_runner(
        monkeypatch,
        audit,
        tmp_path,
        {"pip-audit.json": {"dependencies": deps}},
        1 if expected == "fail" else 0,
    )
    if expected == "error":
        with pytest.raises(CheckError):
            audit.vulnerabilities(
                tmp_path, {}, dict(requirements="requirements.txt"), tmp_path
            )
    else:
        result = audit.vulnerabilities(
            tmp_path, {}, dict(requirements="requirements.txt"), tmp_path
        )
        assert result["status"] == expected
        assert calls[0][0][0][:3] == ["/tool/pip-audit", "--disable-pip", "--no-deps"]
        if expected == "fail":
            assert result["findings"] == [
                dict(
                    file=str(tmp_path / "requirements.txt"),
                    line=1,
                    rule="V-1",
                    message="foo==1 已知漏洞；可用修复版本 ['2']",
                )
            ]


def test_dependency_edges_and_include_boundaries(tmp_path):
    """模块边界、相对导入和 include 规则各自关联实际位置。

    Args:
        tmp_path: 独立源码目录。
    """
    (tmp_path / "core").mkdir()
    (tmp_path / "core/__init__.py").write_text("from . import api\n")
    (tmp_path / "core/api.py").write_text("import outside\nfrom outside import one\n")
    (tmp_path / "native.cc").write_text("#include <bad/api.h>\n#include <good/api.h>\n")
    (tmp_path / "unrelated.py").write_text("import outside\n")
    files = {
        "core/__init__.py": "python",
        "core/api.py": "python",
        "native.cc": "cpp",
        "unrelated.py": "python",
    }
    result = audit.dependencies(
        tmp_path,
        files,
        dict(
            forbidden=[{"from": "core", "to": "outside"}],
            include_forbidden=[{"from": "native", "to": "bad/"}],
        ),
        tmp_path,
    )
    assert result["status"] == "fail"
    assert [(x["file"], x["line"]) for x in result["findings"]] == [
        ("core/api.py", 1),
        ("core/api.py", 2),
        ("core/api.py", 2),
        ("native.cc", 1),
    ]
    assert result["findings"][-1]["message"] == "不允许 include bad/api.h"
    edges = json.loads(Path(result["evidence"]).read_text())
    assert (
        dict(source="core", target="core.api", file="core/__init__.py", line=1) in edges
    )
    assert not audit.prefix_matches("core_extra", "core")
    assert audit.prefix_matches("core.api", "core") and audit.prefix_matches(
        "core", "core"
    )
    with pytest.raises(CheckError):
        audit.dependencies(tmp_path, files, {}, tmp_path)
    (tmp_path / "bad.py").write_text("from .. import x")
    with pytest.raises(CheckError):
        audit.dependencies(
            tmp_path,
            {"bad.py": "python"},
            {"forbidden": [{"from": "a", "to": "b"}]},
            tmp_path,
        )
    assert (
        audit.dependencies(
            tmp_path,
            {"unrelated.py": "python"},
            dict(module_roots=["core"], forbidden=[{"from": "a", "to": "b"}]),
            tmp_path,
        )["status"]
        == "pass"
    )


def test_secrets_empty_binary_size_and_directory(tmp_path):
    """凭据扫描的空输入、二进制与大小限制均不误报为完整通过。

    Args:
        tmp_path: 独立扫描目录。
    """
    with pytest.raises(CheckError):
        audit.secrets(tmp_path, {}, {}, tmp_path)
    (tmp_path / "binary").write_bytes(b"\xff\xfe")
    with pytest.raises(CheckError):
        audit.secrets(tmp_path, {}, {"paths": ["binary"]}, tmp_path)
    (tmp_path / "plain").write_text("x=1")
    assert (
        audit.secrets(tmp_path, {}, {"paths": ["plain"], "max_bytes": 3}, tmp_path)[
            "status"
        ]
        == "pass"
    )
    (tmp_path / "large").write_text("long text")
    result = audit.secrets(tmp_path, {}, {"paths": ["."], "max_bytes": 3}, tmp_path)
    assert result["status"] == "error" and result["skipped"] == ["large"]


@pytest.mark.parametrize(
    "checks,metrics,limit,code,expected",
    [
        ({"ok": True}, {"seconds": 2}, 2, 0, "pass"),
        ({"ok": True}, {"seconds": 3}, 2, 0, "fail"),
        ({"ok": False}, {"seconds": 1}, 2, 1, "fail"),
        ({"ok": True}, {"seconds": 1}, 2, 1, "error"),
        ({}, {}, 2, 0, "error"),
        ({"ok": 1}, {}, 2, 0, "error"),
        ({"ok": True}, {"seconds": True}, 2, 0, "error"),
        ({"ok": True}, {"seconds": float("inf")}, 2, 0, "error"),
        ({"ok": True}, {}, 2, 0, "error"),
    ],
)
def test_acceptance_contract(
    tmp_path, monkeypatch, checks, metrics, limit, code, expected
):
    """验收要求真实布尔判据和有限数值，恰好等于上限允许通过。

    Args:
        tmp_path: 副本目录。
        monkeypatch: 运行边界替换器。
        checks: 业务判据。
        metrics: 数值指标。
        limit: 指标上限。
        code: 命令退出码。
        expected: 预期状态。
    """

    def snapshot(*args):
        """返回已准备的副本。

        Args:
            args: 原始快照参数。
        """
        return tmp_path

    monkeypatch.setattr(acceptance_module, "snapshot", snapshot)
    install_runner(
        monkeypatch,
        acceptance_module,
        tmp_path,
        {"result.json": dict(checks=checks, metrics=metrics)},
        code,
    )
    options = dict(
        report="result.json",
        argv=["test", "{workspace}", "{report}"],
        limits={"seconds": limit},
    )
    if expected == "error":
        with pytest.raises(CheckError):
            acceptance_module.acceptance(tmp_path, {}, options, tmp_path)
    else:
        result = acceptance_module.acceptance(tmp_path, {}, options, tmp_path)
        assert result["status"] == expected
        if expected == "fail":
            assert result["findings"][0]["line"] == 1


@pytest.mark.parametrize(
    "xml,warning,expected",
    [
        (
            "<doxygenindex><compound/></doxygenindex>",
            "a.hh:7: warning: missing param\n",
            "fail",
        ),
        ("<doxygenindex><compound/></doxygenindex>", "unlocated warning\n", "fail"),
        ("<doxygenindex><compound/></doxygenindex>", "", "pass"),
        ("<doxygenindex/>", "", "error"),
        (None, "", "error"),
    ],
)
def test_doxygen_protocol(tmp_path, monkeypatch, xml, warning, expected):
    """文档对象为空或没有 XML 时不能通过，警告保留位置和正文。

    Args:
        tmp_path: 证据目录。
        monkeypatch: 外部工具替换器。
        xml: 模拟生成的索引文本。
        warning: 文档警告文本。
        expected: 预期状态。
    """
    payload = {"doxygen-warnings.log": warning}
    if xml is not None:
        payload["doxygen/xml/index.xml"] = xml
    calls = install_runner(monkeypatch, native, tmp_path, payload)
    if expected == "error":
        with pytest.raises(CheckError):
            native.doxygen(tmp_path, {"a.hh": "cpp"}, {}, tmp_path)
    else:
        result = native.doxygen(
            tmp_path, {"a.hh": "cpp"}, {"executable": "/custom/doxygen"}, tmp_path
        )
        assert result["status"] == expected
        if warning.startswith("a.hh"):
            assert result["findings"] == [
                dict(file="a.hh", line=7, rule="DOXYGEN", message="missing param")
            ]
        elif warning:
            assert result["findings"] == [
                dict(file="", line=1, rule="DOXYGEN", message=warning.strip())
            ]
        assert calls[0][0][0][0] == "/custom/doxygen"
        assert f'INPUT = "{tmp_path}/a.hh"' in (tmp_path / "Doxyfile").read_text()


@pytest.mark.parametrize(
    "body,text,expected",
    [
        ("<testcase><failure/></testcase>", "", 1),
        ("", "", None),
        ("<testcase><skipped/></testcase>", "", None),
        ("<testcase/>", "unexpected memory mapping", None),
        ("<testcase/>", "ASan runtime does not come first", None),
        ("<testcase/>", "LeakSanitizer has encountered a fatal error", None),
    ],
)
def test_ctest_protocol(tmp_path, monkeypatch, body, text, expected):
    """空测试、跳过和运行库失败都属于执行不完整。

    Args:
        tmp_path: JUnit 与日志目录。
        monkeypatch: 工具替换器。
        body: JUnit 用例 XML。
        text: 工具日志。
        expected: 预期执行用例数，None 表示错误。
    """
    calls = install_runner(
        monkeypatch,
        native,
        tmp_path,
        {"run.xml": f"<testsuite>{body}</testsuite>", "tool.log": text},
        8 if expected is not None else 0,
    )
    if expected is None:
        with pytest.raises(CheckError):
            native.test_project(tmp_path, tmp_path, {}, tmp_path, "run")
    else:
        code, log, count = native.test_project(
            tmp_path, tmp_path, {}, tmp_path, "run", True
        )
        assert (code, count) == (8, 1) and log == tmp_path / "tool.log"
        assert calls[0][1]["accepted"] == (0, 8)
        with pytest.raises(CheckError):
            native.test_project(tmp_path, tmp_path, {}, tmp_path, "run")
        assert calls[1][1]["accepted"] == (0,)


def native_workspace(monkeypatch, tmp_path):
    """提供可审查的假构建目录，记录插桩要求。

    Args:
        monkeypatch: 替换构建过程。
        tmp_path: 工程目录。
    """
    build = tmp_path / "build"
    build.mkdir()
    flags = []

    def prepare(root, options, output, extra=""):
        """返回测试构建目录。

        Args:
            root: 原始根目录。
            options: 构建配置。
            output: 证据目录。
            extra: 请求的插桩参数。
        """
        flags.append(extra)
        return tmp_path, build

    monkeypatch.setattr(native, "prepare", prepare)
    return build, flags


@pytest.mark.parametrize(
    "kind,code,expected",
    [("address,undefined", 0, "pass"), ("thread", 8, "fail"), ("combined", 0, "error")],
)
def test_sanitizer_commands(tmp_path, monkeypatch, kind, code, expected):
    """ASan/UBSan 与 TSan 分开构建，运行失败不能通过。

    Args:
        tmp_path: 工程目录。
        monkeypatch: 工具替换器。
        kind: 所选检测类型。
        code: CTest 退出码。
        expected: 预期状态。
    """
    _, flags = native_workspace(monkeypatch, tmp_path)
    install_runner(
        monkeypatch,
        native,
        tmp_path,
        {
            "sanitizer-tests.xml": "<testsuite><testcase>"
            + ("<failure/>" if code else "")
            + "</testcase></testsuite>"
        },
        code,
    )
    if expected == "error":
        with pytest.raises(CheckError):
            native.sanitizers(tmp_path, {}, dict(kind=kind), tmp_path)
    else:
        result = native.sanitizers(tmp_path, {}, dict(kind=kind), tmp_path)
        assert result["status"] == expected and result["tests"] == 1
        assert flags == [
            f"-fsanitize={kind} -fno-sanitize-recover=all -fno-omit-frame-pointer -g"
        ]
        assert bool(result["findings"]) == (code != 0)
        if code != 0:
            assert result["findings"][0]["line"] == 1


@pytest.mark.parametrize(
    "lines,minimum,expected",
    [
        ([{"count": 1}, {"count": 0}, {"count": 0, "gcovr/noncode": True}], 50, "pass"),
        ([{"count": 1}, {"count": 0}], 51, "fail"),
        ([], 50, "error"),
    ],
)
def test_cpp_coverage_boundaries(tmp_path, monkeypatch, lines, minimum, expected):
    """覆盖率排除非代码行，等于阈值通过，无可执行行报错。

    Args:
        tmp_path: 工程目录。
        monkeypatch: 工具替换器。
        lines: 覆盖率行记录。
        minimum: 覆盖率门槛。
        expected: 预期状态。
    """
    _, flags = native_workspace(monkeypatch, tmp_path)
    install_runner(
        monkeypatch,
        native,
        tmp_path,
        {
            "coverage-tests.xml": "<testsuite><testcase/></testsuite>",
            "gcovr.json": {
                "files": [
                    dict(file="a.cc", lines=lines),
                    dict(file="generated.cc", lines=[{"count": 0}]),
                ]
            },
        },
    )
    if expected == "error":
        with pytest.raises(CheckError):
            native.cpp_coverage(
                tmp_path, {"a.cc": "cpp"}, dict(minimum=minimum), tmp_path
            )
    else:
        result = native.cpp_coverage(
            tmp_path, {"a.cc": "cpp"}, dict(minimum=minimum), tmp_path
        )
        assert result["status"] == expected and result["coverage"] == 50
        assert flags == ["--coverage -O0 -g"]
        if expected == "fail":
            assert result["findings"][0]["line"] == 1


@pytest.mark.parametrize(
    "sources,duplicates,expected",
    [
        (0, [], "error"),
        (1, [], "pass"),
        (
            2,
            [
                dict(
                    firstFile=dict(name="a.cc", start=3),
                    secondFile=dict(name="b.cc", start=7),
                )
            ],
            "fail",
        ),
    ],
)
def test_cpp_duplicate_protocol(tmp_path, monkeypatch, sources, duplicates, expected):
    """重复检测必须实际扫描文件，发现项保留两个文件的位置。

    Args:
        tmp_path: 证据目录。
        monkeypatch: 工具替换器。
        sources: 扫描文件数。
        duplicates: 克隆记录。
        expected: 预期状态。
    """
    install_runner(
        monkeypatch,
        native,
        tmp_path,
        {
            "jscpd-report.json": dict(
                statistics=dict(total=dict(sources=sources)), duplicates=duplicates
            )
        },
    )
    if expected == "error":
        with pytest.raises(CheckError):
            native.cpp_duplicates(tmp_path, {"a.cc": "cpp"}, {}, tmp_path)
    else:
        result = native.cpp_duplicates(tmp_path, {"a.cc": "cpp"}, {}, tmp_path)
        assert result["status"] == expected
        if expected == "fail":
            assert result["findings"] == [
                dict(
                    file="a.cc",
                    line=3,
                    rule="CPP-DUPLICATE",
                    message="与 b.cc:7 存在克隆候选",
                )
            ]
