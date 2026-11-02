/**
 * @file distance.hh
 * @brief 一维距离计算示例，输入坐标采用米。
 */
#pragma once

/**
 * @brief 返回两点间的非负距离。
 * @param start_m 起点坐标，单位米。
 * @param end_m 终点坐标，单位米。
 * @return 两点距离，单位米。
 */
inline double Distance(double start_m, double end_m)
{
    const double delta = end_m - start_m;
    return delta >= 0 ? delta : -delta;
}
