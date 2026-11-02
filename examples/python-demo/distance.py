"""演示带单位约束的直线距离计算。"""


def distance(start_m: float, end_m: float) -> float:
    """返回两个一维坐标之间的距离。

    Args:
        start_m: 起点坐标，单位 m。
        end_m: 终点坐标，单位 m。

    Returns:
        非负距离，单位 m。
    """
    return abs(end_m - start_m)
