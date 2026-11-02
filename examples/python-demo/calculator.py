"""用一维位移演示类型、覆盖率和变异检测。"""


def displacement(start_m: float, end_m: float) -> float:
    """计算带方向的一维位移。

    Args:
        start_m: 起点坐标，单位 m。
        end_m: 终点坐标，单位 m。

    Returns:
        终点减起点，单位 m，可为负值。
    """
    return end_m - start_m
