"""保护位移数值，并用性质测试验证平移不变性。"""

import pytest
from hypothesis import given, strategies as st
from calculator import displacement


@pytest.mark.parametrize("start,end,expected", [(1, 3, 2), (3, 1, -2), (2, 2, 0)])
def test_displacement(start, end, expected):
    """不同方向和相同坐标均产生正确位移。"""
    assert displacement(start, end) == expected


@given(st.integers(-1000, 1000), st.integers(-1000, 1000), st.integers(-1000, 1000))
def test_translation(start, end, offset):
    """同时平移两个坐标不改变位移。"""
    assert displacement(start + offset, end + offset) == displacement(start, end)
