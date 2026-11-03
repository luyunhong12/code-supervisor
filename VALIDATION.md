# 0.2.0 实际验证记录

日期：2026-11-02。开发暂存目录 `/tmp/code-supervisor-v2`，最终安装目录
`/home/yh/Project/code-supervisor`。本轮未修改车辆原工程源码或构建目录。

## 已执行

| 验证 | 结果 |
|---|---|
| 最终环境运行 bootstrap.sh | 成功；固定Python/Node依赖和原三工具提交安装完成；doctor全部可发现 |
| 自身测试 | 40项通过，包括真实工具反例与协议边界 |
| 自身full | 中文文档、Black、Ruff、测试通过 |
| Python示例deep | 9项检查通过；真实coverage与原版变异算子运行 |
| C++示例deep | 9项检查通过；真实构建、clang-tidy、Doxygen、覆盖率、ASan/UBSan、有限变异 |
| 人为整数溢出 | ASan/UBSan运行返回失败，证明错误不是被恢复后假通过 |
| 已知脆弱requests版本 | pip-audit检出5条已知漏洞；查询只发送公开包名/版本 |
| TSan宿主探测 | 执行错误：unexpected memory mapping；保留环境不兼容状态 |
| 车辆副本代码验收 | 12包构建，607项测试，0错误、0失败、0跳过 |
| 车辆制动算法 | 新构建、clang-tidy、行覆盖率100%、ASan/UBSan通过；2项复杂度诊断 |
| 车辆制动有限变异 | 31个实际重新编译/测试的变异：13检出，18存活；需要判断等价或测试不足 |

源码安全反例 eval、弱断言、结构重复、错返回类型、相对导入越界、错Doxygen参数、
过期验收报告、矛盾退出状态、顶层符号链接等已纳入测试。
修复了生成代码混入C++覆盖率分母，以及 Doxygen 1.9.8仅生成XML时对已写参数文档的误报：
同时生成HTML/XML后，正确文档通过，错误参数反例仍然检出。

## 证据位置

- 自身：`.generated/supervisor/20261102T083737Z-1d24012b/report.txt`
- Python：`examples/python-demo/.generated/supervisor/20261102T083744Z-e0288234/report.txt`
- C++：`examples/cpp-demo/.generated/supervisor/20261102T083746Z-a1378080/report.txt`
- 车辆、运行时及漏洞查询证据归档在 `.generated/release-0.2/`。
- 原始暂存目录 `/tmp/supervisor-carriage-code`、`/tmp/supervisor-carriage-brake` 保留，
  归档报告中的绝对证据路径指向原暂存目录；归档内保留相同相对结构。

## 尚不能声称的内容

- 未执行完整整车 baseline/experimental物理仿真。本轮验证了代码验收与独立制动路径。
- TSan在当前宿主未成功运行；安装或编译通过不代表线程检测通过。
- 本地没有GitHub远程地址，工作流已提供，但没有远程Actions运行记录。
- 自身full测试通过不等于自身全部函数CRAP<10；本轮没有跑工具全源码的穷举变异。
- 示例通过不代表其他工程自动符合全部规范。新增工程必须提供正确配置和测试依赖。
- C++变异是有限二元算子实现，不是Mull；没有输出未经可靠匹配的C++ CRAP。

## 环境

Ubuntu24.04、Python3.12、GCC13、CMake3.28.3，Python工具见锁定清单。
本机Doxygen1.9.8来自Ubuntu官方包 `1.9.8+ds-2ubuntu0.1`，仅解压到本地 `.tools/doxygen`，
没有修改系统安装。jscpd4.0.5装在本地 `.tools/node_modules`。
三原版工具安装提交见 requirements-ub.txt；源码与二进制不提交到本仓库。

## 本轮重要动作及原因

1. 接入专用适配器，读取真实工具结果，避免退出0、空覆盖或未执行产生假通过。
2. 构建/变异改用显式输入副本，重新编译C++；对原源码保留哈希证据。
3. 增加反例验证、状态门禁和报告协议，区分工具故障与确认问题。
4. 增加安装脚本、跨项目配置、中文24项工作表、GitHub工作流和本地钩子。
5. 实际复验两个语言示例及车辆代码入口，记录仍未验证的环境与业务范围。

## 2026-11-03 参数规则增量验证

新增parameter-docs，11项正反例通过，完整测试51项通过。生成车辆副本配置的命令验证通过。车辆最新副本构建12包、631测试通过；参数规则识别3184项，1079条缺少中文说明诊断，16个文件未完整检查（12个C++宏语法、4个JSON/XML配置）。这些是检查结果，不是规则全部通过。详见车辆工程.generated/supervisor-review-20261103-parameters/report.md。
