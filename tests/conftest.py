"""优先执行快速规则测试，减少变异失败后无必要的工具链运行。"""


def pytest_collection_modifyitems(items):
    """仅调整执行顺序，保留全部已收集测试。

    Args:
        items: pytest 已收集的测试列表，原地稳定排序。
    """
    items.sort(key=integration_priority)


def integration_priority(item):
    """将真实工具链集成测试放在规则测试之后。

    Args:
        item: pytest 测试项。
    """
    return item.path.name in {
        "test_advanced.py",
        "test_supervisor.py",
        "test_native_usage.py",
        "test_required_scope_paths.py",
    }
