/**
 * @file test_distance.cc
 * @brief 检查两个方向的距离，防止算术修改逃过测试。
 */
#include "distance.hh"

/**
 * @brief 执行距离断言。
 * @return 通过返回0，距离错误返回1。
 */
int main()
{
    if (Distance(1.0, 3.0) != 2.0 || Distance(3.0, 1.0) != 2.0)
    {
        return 1;
    }
    return 0;
}
