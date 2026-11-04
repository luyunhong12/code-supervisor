# 能力与验证边界（0.2.0）

下列为已实现接口，不意味着每个目标工程已经配置或全部通过。

| 检查 ID | 使用实现 | 检测内容与边界 |
|---|---|---|
| python-docs / black / ruff | AST、Black、Ruff | 中文 Google 文档基础规则、格式、语法及静态错误；不是 Google 全文认证 |
| parameter-docs | AST、tree-sitter、YAML语法节点 | 逐名检查函数参数与YAML配置键中文说明；解析失败/其他配置格式明确报告，不能证明语义真实 |
| pyright | Pyright | 静态类型；缺存根保留诊断，动态行为仍需测试 |
| dependencies | 本项目 AST/import/include 规则 | 明确禁止的模块依赖，支持相对导入；不推断架构合理性，不检查动态加载 |
| security | Bandit | Python 安全模式；候选有误报，不覆盖完整攻击面 |
| secrets | detect-secrets | 指定文本范围的疑似凭据，只报位置/类型，不联网验证，不扫 Git 历史 |
| vulnerabilities | pip-audit | 完整固定 Python 依赖清单的已知漏洞；不覆盖 C++、ROS、系统包和未知漏洞 |
| crapper | 原版 crapper + 本次 coverage | 函数复杂度与真实覆盖率计算 CRAP，默认 CRAP>=10 报告 |
| dryer | 原版 dryer | 结构重复候选，默认相似度0.8/4行/20节点；零候选不等于无重复 |
| mutator | 原版 mutator 算子 + 本项目隔离执行器 | 每个变异重新测试，存活/未覆盖/预算不足分别记录；未用原版 worker 调度器 |
| cpp-docs / doxygen | tree-sitter-cpp + 官方 Doxygen | 中文基础说明、签名/参数文档警告、HTML/XML；宏不完整解析不能当通过 |
| cpp-build | CMake + CTest | 副本内新构建及非空测试，跳过项不算通过 |
| clang-tidy | clang-tidy | 本次生成编译数据库，编译器分析、bugprone、performance 规则 |
| cpp-complexity | Lizard | 函数圈复杂度；**没有可靠函数覆盖映射时不计算 C++ CRAP** |
| cpp-duplicates | jscpd | token 克隆候选，支持 C++；不同于 dryer 结构相似度 |
| cpp-coverage | GCC + gcovr | 新插桩、新测试、所选源码行覆盖；不混入 CMake 探针；不是正确率 |
| cpp-sanitizers | ASan + UBSan | 实际执行路径上的内存/未定义行为，UBSan 禁止错误恢复以免假通过 |
| cpp-thread | 单独 TSan 构建 | 测试实际触发的竞争；宿主不兼容返回错误，不能与 ASan 同构建 |
| cpp-mutation | 本项目有限二元算子后端 | 每项清理重编译再测试；**不是 Mull**，不覆盖其全部算子/宏/模板情形 |
| acceptance | 结构化验收协议 | 业务布尔判据、数值性能上限；需项目自己提供真实判据与测量 |
| doctor / compare / SARIF | 本项目 | 环境可用性、历史差异、可消费机器报告；不掩盖执行失败 |

## 采用和未采用的项目

本版实际采用 Pyright、Bandit、detect-secrets、pip-audit、Lizard、jscpd、clang-tidy、
coverage/gcovr、Hypothesis 示例性质测试、官方 Doxygen，以及原版 ub 三工具。
原先讨论的 Tach、Gitleaks、OSV-Scanner、CodeChecker、Mull、MegaLinter、reviewdog
**没有全部安装和叠加**。本版用明确边界规则、上述安全工具及有限 C++ 变异覆盖相应部分需求，
不能宣传成这些候选工具的完整功能集合。GitHub 工作流负责执行和保留报告，不自动贴审查评论。

## 重要限制

- Google Python 全文、架构职责、单位、模型真实性、需求遗漏仍由 AI/人审查。
- Python 原 ub 工具只接收选定的 `.py`；无后缀入口不能悄悄忽略。
- Python 测量使用本工具解释器与显式 pytest 参数；禁用自动插件发现，所需插件用 `-p` 指定。
- 变异存活是待审查线索，可能等价；预算耗尽、没有有效变异、未覆盖均不能伪报通过。
- CMake 入口必须显式提供，ROS 全工程走项目验收入口；单个独立 C++ 测试不能代表所有插件。
- 隔离复制保护原路径上的源码；不是容器沙箱。测试可访问外部路径，需信任项目代码。
- 默认不专门分析 QML、shell、SDF/YAML 语义；项目验收可接入这些检查。
- 安全漏洞库请求失败、解析失败、空覆盖、空测试返回错误，不当作没有问题。

## 来源与版本

原三工具固定 Git 提交见 `requirements-ub.txt`，Python 直接版本见 `pyproject.toml`，
本机完整 Python 环境清单见 `requirements-lock.txt`，Node 锁见 `tools/package-lock.json`。
系统编译器和 Doxygen 受宿主环境管理，跨系统结果可能变化；诊断不应据此量化“正确率提升百分比”。
没有复制原 ub-mode 的完整 Skill，不承诺逐字实现其全部24条语义审查原则。

- [Google Python](https://google.github.io/styleguide/pyguide.html)、[Doxygen](https://www.doxygen.nl/manual/config.html)
- [ub-mode](https://github.com/unclebob/ub-mode)、[crapper](https://github.com/unclebob/crapper)、[dryer](https://github.com/unclebob/dryer)、[mutator](https://github.com/unclebob/mutator)
- [Pyright](https://github.com/microsoft/pyright)、[Bandit](https://github.com/PyCQA/bandit)、[detect-secrets](https://github.com/Yelp/detect-secrets)、[pip-audit](https://github.com/pypa/pip-audit)
- [Lizard](https://github.com/terryyin/lizard)、[jscpd](https://github.com/kucherenko/jscpd)、[clang-tidy](https://clang.llvm.org/extra/clang-tidy/)

第三方实现由安装器获取，本仓库不提交工具二进制；再次分发时仍应遵守各项目许可证。

## Qt 参数文档解析边界

C++ 参数检查识别独立行 `Q_OBJECT`、简单的
`Q_PROPERTY(TYPE name READ getter NOTIFY signal)` 及 `signals:`，
保留源码行号；注释和字符串中的同名文本不会作为宏处理。
复杂或多行属性宏仍可能产生解析错误，需要单独适配，不能当作已检查通过。
这只是参数文档解析支持，不代表执行 Qt 元对象编译器或验证信号槽行为。
