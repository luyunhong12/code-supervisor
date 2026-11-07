# 第三方来源与授权

本仓库的原创代码和文档使用 [MIT](LICENSE)。下表区分随仓库分发的改编内容与用户安装时另行取得的工具。Supervisor 的许可证不替代这些项目的许可证。

| 来源（链接指向核验版本的许可证） | 许可证 | 在 Supervisor 中的使用方式 |
| --- | --- | --- |
| [Robert C. Martin：ub-mode](https://github.com/unclebob/ub-mode/blob/3da62bf3fcfd2034de41f30d920d2739e566171f/LICENSE) | MIT | 中文工作表参考其审查原则并补充工具和复核方法，保留[完整版权及许可声明](licenses/ub-mode-MIT.txt)。上游 README 也致谢了 [@poteto](https://github.com/poteto) 的规则。 |
| [crapper](https://github.com/unclebob/crapper/blob/6fd92c4c9bcc56efb64a2f8743d5a2993bcfd42d/LICENSE) | 0BSD | 安装时从上游获取，在 Python 适配器中调用复杂度和覆盖率分析。 |
| [dryer](https://github.com/unclebob/dryer/blob/66ff6d21a42c04afcad89c78a80066176d1294b0/LICENSE) | 0BSD | 安装时从上游获取，查找结构相似的代码。 |
| [mutator](https://github.com/unclebob/mutator/blob/a5a0cb803b66e0cdb8bf471b3b08af701d424a41/LICENSE) | 0BSD | 安装时从上游获取变异算子，由本项目的执行器测试。 |

三个工具的许可证文本相同，版权归 Robert C. Martin，见[上游原文](licenses/ub-tools-0BSD.txt)。固定提交见 [requirements-ub.txt](requirements-ub.txt)。项目的通用编码和结构规范来自同一维护者的[车辆工程](https://github.com/luyunhong12/moving_carriage_sensors)，没有把车辆模型、CAD 资源或仿真报告纳入本工具的授权。

## 安装依赖与发布范围

这个仓库发布 Supervisor 源码、示例、配置与文档。安装器从各自来源取得 Python、Node 依赖及语法解析器；仓库不附带虚拟环境、node_modules、解析器二进制或系统工具。以下是直接依赖的声明摘要，具体版权、例外条款和随包声明以相应版本原件为准。

| 安装时获取的组件 | 对应许可证声明 |
| --- | --- |
| Black、Ruff、tree-sitter、tree-sitter-cpp、pytest、Pyright、Lizard、tree-sitter-language-pack、jscpd | MIT |
| coverage、Bandit、detect-secrets、pip-audit、edn-format | Apache-2.0 |
| Hypothesis | MPL-2.0 |
| gcovr | BSD-3-Clause |
| clang-tidy / LLVM | Python 分发包声明 Apache 2.0；LLVM 组件另见 [LLVM 的许可与例外](https://llvm.org/docs/DeveloperPolicy.html#licensing)。 |

Python 和 Node 的版本分别见 [Python 锁定清单](requirements-lock.txt)及 [Node 锁文件](tools/package-lock.json)。GCC、CMake/CTest、Doxygen 等由运行环境提供。若改为分发容器、离线安装包或含依赖的二进制，应按该产物实际包含的组件（包括传递依赖）另行检查并随附相应声明。
