# 第一版能力与第三方工具

| 能力 | 0.1.0 状态 | 边界 |
|---|---|---|
| Python 中文文档存在性 | 已实现 AST 检查 | 不证明说明真实 |
| Python Google 文档格式 | Ruff 子集＋基本引号/标签检查 | 不认证完整 Google Style Guide；不强制简单函数有所有分区 |
| Python 排版 | Black 24.10.0 内存比较 | 源码范围以 supervisor 配置为准；仅支持明确列出的 Black 配置 |
| Python 静态问题 | Ruff 0.14.3 固定规则 F/E4/E7/E9 | 无类型推断或完整安全检查 |
| C++ Doxygen | tree-sitter-cpp 0.23.4 基本检查 | 文件 @file/@brief、类型/函数前中文注释；不检查全部参数、成员或宏展开 |
| 官方 Doxygen 完整生成 | 未接入 | 基本解析器不是 Doxygen 替代品 |
| 自定义构建与测试 | 已实现显式 argv、退出码映射和超时回收 | 需项目提供可信命令；命令自行决定测试范围 |
| crapper / dryer / mutator | 待专用适配，full/deep 配置中明确未完成 | 不以通用命令退出码冒充工具语义；dryer 有候选也可能返回0 |
| C++ 编译器分析、覆盖率、Sanitizer、Mull | 未接入 | 必须真实构建与运行后才可报告 |
| 类型、模块依赖、安全扫描 | 后续接入 | Pyright、Tach、Gitleaks、OSV-Scanner 为候选 |
| AI 辅助审查 | 提供 AI_REVIEW.md | 无内置模型、无 API 调用、无 Skill |

## 固定规则

Ruff 使用显式规则 F、E4、E7、E9、D200、D205、D209、D300、D405、D410、D411、D416。
不启用英文祈使句和英文句号检查，避免违背中文约定；不强制简单函数填写全部栏目。
复杂接口缺少适用 Args/Returns/Raises、参数形状和单位等仍需人工判断。
C++ 含复杂宏导致解析失败时返回 error；解析成功也不表示编译通过。
第一版不对 .qml/.sh/.yaml 等文件做专用语法检测，不将它们算入源码覆盖统计。

## 后续接入顺序

1. ub 工具专用解析器：必须检查扫描范围、实际覆盖率、候选记录和基线测试，
   防止空扫描、coverage缺失、dryer返回0、mutator跳过未覆盖代码造成假通过。
   变异测试默认使用隔离快照，核对原测试确实执行变异程序。
2. CodeChecker/clang-tidy：生成并核对 compile_commands.json，使用项目真实编译配置。
3. C++ Doxygen 官方警告、覆盖率、Sanitizer。ASan/UBSan 与 TSan 分别构建验证。
4. pre-commit 快速检查；reviewdog 仅作结果呈现；MegaLinter 按需启用，不重复跑相同检查。
5. 类型、依赖边界、性质测试和安全检测，逐项目标定。

## 来源及许可边界

本项目调用第三方包，没有复制它们的实现。固定直接依赖版本，安装后保存完整环境清单。
原 ub-mode 仅作为工作原则参考，没有复制其完整 SKILL.md 或工具源码。
若将来打包/分发第三方二进制，需保留对应许可证和声明。

- Google Python：https://google.github.io/styleguide/pyguide.html
- Doxygen：https://www.doxygen.nl/manual/config.html
- Black：https://github.com/psf/black
- Ruff：https://github.com/astral-sh/ruff
- tree-sitter-cpp：https://github.com/tree-sitter/tree-sitter-cpp
- ub-mode：https://github.com/unclebob/ub-mode
- crapper / dryer / mutator：https://github.com/unclebob
- pre-commit：https://github.com/pre-commit/pre-commit
- CodeChecker：https://github.com/Ericsson/codechecker
- MegaLinter：https://github.com/oxsecurity/megalinter
- reviewdog：https://github.com/reviewdog/reviewdog

规范不是正确性证明。项目例外必须有理由、范围和复查依据，不能通过全局关闭检查消除问题。
