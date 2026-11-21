"""外部报告必须对应请求范围、包含完整结果并与退出码一致。"""

import pytest
from code_supervisor import audit, native
from code_supervisor.tasks import CheckError
from test_tool_contracts import install_runner


@pytest.mark.parametrize(
    "deps",
    [
        [dict(name="other", version="1", vulns=[])],
        [dict(name="foo", version="2", vulns=[])],
        [dict(name="foo", version="1")],
        [dict(name="foo", version="1", vulns=None)],
        [dict(name="foo", version="1", vulns={})],
        [dict(name="foo", version="1", vulns=[None])],
        [dict(name="foo", version="1", vulns=[{}])],
        [dict(name="foo", version="1", vulns=[dict(id="")])],
        [dict(name="foo", version="1", vulns=[dict(id=1)])],
        [dict(name=None, version="1", vulns=[])],
        [dict(name="foo", version=1, vulns=[])],
        [dict(name="bad name", version="1", vulns=[])],
        [dict(name="foo", version="invalid version", vulns=[])],
        [dict(name="foo", version="1", vulns=[], skip_reason="offline")],
        [None],
        [],
        {},
        None,
    ],
)
def test_vulnerability_rejects_incomplete_or_mismatched_report(
    tmp_path, monkeypatch, deps
):
    """缺项、字段类型错误、跳过或错误依赖不能成为无漏洞证据。

    Args:
        tmp_path: 依赖清单和证据目录。
        monkeypatch: 外部工具替换器。
        deps: 不完整或与清单不匹配的依赖结果。
    """
    (tmp_path / "requirements.txt").write_text("foo==1\n")
    install_runner(
        monkeypatch, audit, tmp_path, {"pip-audit.json": {"dependencies": deps}}
    )
    with pytest.raises(CheckError):
        audit.vulnerabilities(
            tmp_path, {}, dict(requirements="requirements.txt"), tmp_path
        )


@pytest.mark.parametrize("payload", [[], None, {}, "null"])
def test_vulnerability_requires_report_mapping(tmp_path, monkeypatch, payload):
    """顶层报告结构无效时明确拒绝。

    Args:
        tmp_path: 依赖清单和证据目录。
        monkeypatch: 工具替换器。
        payload: 缺少依赖结果映射的报告。
    """
    (tmp_path / "requirements.txt").write_text("foo==1\n")
    install_runner(monkeypatch, audit, tmp_path, {"pip-audit.json": payload})
    with pytest.raises(CheckError):
        audit.vulnerabilities(
            tmp_path, {}, dict(requirements="requirements.txt"), tmp_path
        )


@pytest.mark.parametrize(
    "code,vulns,expected",
    [
        (0, [], "pass"),
        (1, [dict(id="V-1")], "fail"),
        (1, [], "error"),
        (0, [dict(id="V-1")], "error"),
    ],
)
def test_vulnerability_exit_consistency(tmp_path, monkeypatch, code, vulns, expected):
    """无漏洞与有漏洞分别对应退出码零和一，矛盾证据报执行错误。

    Args:
        tmp_path: 证据目录。
        monkeypatch: 工具替换器。
        code: 工具退出码。
        vulns: 工具报告的漏洞列表。
        expected: 预期检查状态。
    """
    (tmp_path / "requirements.txt").write_text("foo==1\n")
    install_runner(
        monkeypatch,
        audit,
        tmp_path,
        {
            "pip-audit.json": dict(
                dependencies=[dict(name="foo", version="1", vulns=vulns)]
            )
        },
        code,
    )
    if expected == "error":
        with pytest.raises(CheckError, match="退出码"):
            audit.vulnerabilities(
                tmp_path, {}, dict(requirements="requirements.txt"), tmp_path
            )
    else:
        assert (
            audit.vulnerabilities(
                tmp_path, {}, dict(requirements="requirements.txt"), tmp_path
            )["status"]
            == expected
        )


def test_vulnerability_normalized_identity_and_order(tmp_path, monkeypatch):
    """包名合法别名、等价版本和结果顺序不影响依赖身份校验。

    Args:
        tmp_path: 证据目录。
        monkeypatch: 工具替换器。
    """
    (tmp_path / "requirements.txt").write_text("Foo_Bar==1.0\nsecond==2\n")
    deps = [
        dict(name="second", version="2.0", vulns=[]),
        dict(name="foo-bar", version="1.0.0", vulns=[]),
    ]
    install_runner(
        monkeypatch, audit, tmp_path, {"pip-audit.json": dict(dependencies=deps)}
    )
    assert (
        audit.vulnerabilities(
            tmp_path, {}, dict(requirements="requirements.txt"), tmp_path
        )["status"]
        == "pass"
    )


def test_vulnerability_duplicate_cannot_replace_missing_package(tmp_path, monkeypatch):
    """报告数量相同但重复一项、漏掉另一项也必须拒绝。

    Args:
        tmp_path: 证据目录。
        monkeypatch: 工具替换器。
    """
    (tmp_path / "requirements.txt").write_text("foo==1\nbar==2\n")
    deps = [dict(name="foo", version="1", vulns=[])] * 2
    install_runner(
        monkeypatch, audit, tmp_path, {"pip-audit.json": dict(dependencies=deps)}
    )
    with pytest.raises(CheckError, match="清单"):
        audit.vulnerabilities(
            tmp_path, {}, dict(requirements="requirements.txt"), tmp_path
        )


@pytest.mark.parametrize(
    "code,body,expected",
    [
        (0, "<testcase/>", "pass"),
        (8, "<testcase><failure/></testcase>", "fail"),
        (8, "<testcase><error/></testcase>", "fail"),
        (0, "<testcase><failure/></testcase>", "error"),
        (0, "<testcase><error/></testcase>", "error"),
        (8, "<testcase/>", "error"),
    ],
)
def test_ctest_junit_exit_consistency(tmp_path, monkeypatch, code, body, expected):
    """成功、用例失败和矛盾的 JUnit 证据分别分类。

    Args:
        tmp_path: JUnit 与日志目录。
        monkeypatch: 工具替换器。
        code: CTest 退出码。
        body: JUnit 测试用例。
        expected: 预期分类。
    """
    install_runner(
        monkeypatch,
        native,
        tmp_path,
        {"ctest.xml": "<testsuites><testsuite>" + body + "</testsuite></testsuites>"},
        code,
    )
    if expected == "error":
        with pytest.raises(CheckError, match="退出码"):
            native.test_project(tmp_path, tmp_path, {}, tmp_path, "ctest", True)
    else:
        result = native.test_project(tmp_path, tmp_path, {}, tmp_path, "ctest", True)
        assert result[0] == code and result[2] == 1


@pytest.mark.parametrize(
    "options,expected", [({}, 120), ({"timeout": 1}, 1), ({"timeout": 0.25}, 0.25)]
)
def test_bandit_forwards_configured_timeout(tmp_path, monkeypatch, options, expected):
    """安全扫描传递明确超时，未配置时保留默认值。

    Args:
        tmp_path: 证据目录。
        monkeypatch: 外部工具替换器。
        options: 安全扫描配置。
        expected: 实际运行边界应收到的秒数。
    """
    calls = install_runner(
        monkeypatch, audit, tmp_path, {"bandit.json": dict(errors=[], results=[])}
    )
    assert (
        audit.security(tmp_path, {"a.py": "python"}, options, tmp_path)["status"]
        == "pass"
    )
    args, kwargs = calls[0]
    assert kwargs.get("timeout", args[4] if len(args) > 4 else 120) == expected


def test_invalid_pinned_package_name_rejected_before_execution(tmp_path, monkeypatch):
    """非法发行包名即使报告同名也应在调用工具前拒绝。

    Args:
        tmp_path: 锁定清单与证据目录。
        monkeypatch: 工具替换器。
    """
    (tmp_path / "requirements.txt").write_text("-bad==1\n")
    calls = install_runner(
        monkeypatch,
        audit,
        tmp_path,
        {
            "pip-audit.json": {
                "dependencies": [dict(name="-bad", version="1", vulns=[])]
            }
        },
    )
    with pytest.raises(CheckError, match="名称或版本无效"):
        audit.vulnerabilities(
            tmp_path, {}, dict(requirements="requirements.txt"), tmp_path
        )
    assert calls == []
