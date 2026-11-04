"""独立车辆验收副本必须保留显式参数文档，不能退回未支持配置。"""

import json
from pathlib import Path
import runpy
import sys
import tomllib

import pytest


@pytest.mark.parametrize("missing", [False, True])
def test_prepare_keeps_documentation_mapping(tmp_path, monkeypatch, missing):
    """文档随副本复制并被配置引用，声明存在但文件缺失时明确失败。

    Args:
        tmp_path: 最小车辆工程与隔离输出目录。
        monkeypatch: 临时命令行参数。
        missing: 是否故意省略被引用的Markdown文件。
    """
    root = tmp_path / "project"
    for name in ["src/demo/config", "tools", "model", "docs", "supervisor"]:
        (root / name).mkdir(parents=True)
    for name in ["pyproject.toml", "pytest.ini"]:
        (root / name).write_text("")
    (root / "src/demo/config/data.json").write_text('{"x":1}')
    if not missing:
        (root / "docs/data.md").write_text("| /x | 输入，无量纲。 |")
    (root / "supervisor/parameters.toml").write_text(
        '[settings.parameter-docs.documentation]\n"src/demo/config/data.json"="docs/data.md"\n'
    )
    script = Path(__file__).resolve().parents[1] / "scripts/prepare_carriage.py"
    module = runpy.run_path(str(script))
    output = tmp_path / "audit"
    monkeypatch.setattr(sys, "argv", [str(script), str(root), str(output)])
    if missing:
        with pytest.raises(ValueError, match="缺少参数说明"):
            module["main"]()
        return
    module["main"]()
    work = output / "workspace"
    config = tomllib.loads((work / "supervisor.toml").read_text())
    assert config["settings"]["parameter-docs"]["documentation"] == {
        "src/demo/config/data.json": "docs/data.md"
    }
    assert (work / "docs/data.md").read_bytes() == (root / "docs/data.md").read_bytes()
    assert json.loads((work / "supervisor-copy.json").read_text())["origin"] == str(
        root
    )
