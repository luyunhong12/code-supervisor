# 代码督导队 0.1.0

一个独立、跨项目的命令行检查工具，基础检查不调用 AI。给 AI 的工作说明是
[AI_REVIEW.md](AI_REVIEW.md)，不是 Skill，也不需要安装 Skill。

## 已能使用的内容

- Python：Google 风格中文文档基础规则、Black 排版、Ruff 静态检查。
- C++：Doxygen 中文文件/类型/函数概述的语法树检查。
- 扫描包含未跟踪文件与无后缀 Python 入口；排除生成物和符号链接。
- 唯一编号的中文报告与 JSON、源码 SHA256、Git 状态、配置/规范哈希。
- 显式项目命令、超时回收、执行失败/未执行区分，以及检查期间源码变化检测。

这只是第一版基础检查。完整 Google 指南、官方 Doxygen、C++ 编译器检查、
ub 三工具专用适配及物理验收尚未完成，见[能力表](docs/capabilities.md)。
退出0只代表本次配置已执行的规则通过，不是项目没有错误。

## 安装

需要 Linux 和 Python 3.11+；建议 Python 3.12。工具运行在自己的虚拟环境，不加入业务运行依赖。

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

无需激活环境，使用工具绝对路径即可。版本固定在 pyproject.toml；本次安装的完整依赖清单保存在 requirements-lock.txt。

## 直接试用

在本工具目录执行：

```bash
.venv/bin/supervisor check examples/python-demo
.venv/bin/supervisor check examples/cpp-demo
```

检查车辆工程，配置保存在督导队内，不需要修改车辆源码：

```bash
.venv/bin/supervisor check /home/yh/Project/moving_carriage_sensors \
  --config profiles/moving-carriage.toml \
  --output .generated/carriage
```

## 接入另一个项目

```bash
.venv/bin/supervisor init /path/to/project
.venv/bin/supervisor check /path/to/project
```

init只创建 supervisor.toml，不覆盖已有文件。确认 source/exclude/policy 后执行。
检查不会修改源码，但会在指定输出目录生成报告；默认输出到目标工程 `.generated/supervisor`。
工具不自动安装依赖、不提交、不推送、不调用网络 API。

## 构建或测试

配置可以定义可信命令（数组，不使用 shell 拼接）：

```toml
[[commands]]
id = "tests"
argv = ["/path/to/project-python", "-m", "pytest", "-q"]
profile = "full"
timeout = 120
finding_codes = [1]
```

`{python}` 表示督导队自己的解释器，不是目标项目解释器；ROS 测试应指定正确环境或专用入口脚本。

```bash
.venv/bin/supervisor check /path/to/project --profile full --run-commands
```

必须读取并信任配置才使用 --run-commands。它明确允许配置命令执行，命令可能写入构建/测试产物；
这不是沙箱。Linux 超时清理本次进程组，不能保证清理主动脱离会话的守护进程。
quick/full/deep是执行分层，不会自动发明项目缺失的测试。

## 看报告

- `report.txt`：中文检查结果及问题位置。
- `report.json`：原始状态、范围、规则、哈希、工具版本和命令。
- 工具日志：完整输出，可能含业务数据，应留在本地；不自动上传。

退出码：0本次已执行范围通过；1发现问题；2执行错误或必需检查未完成。
未配置的完整检查显式为“未执行”；无适用源码为“不适用”；完全空扫描拒绝通过。
语义审查始终单列，不把机器通过当作人工审查完成。

## 给 AI 使用

告诉 AI：

> 阅读 /home/yh/Project/code-supervisor/AI_REVIEW.md，按其中流程检查目标工程。

AI读取Markdown后调用同一命令行，并审查工具无法判断的接口契约和业务行为。
文档本身不授权自动改代码或推送。

## 自身验证

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
.venv/bin/supervisor check .
```

仅督导队自身测试关闭环境自动加载的 pytest 插件，避免 ROS 的插件污染工具测试环境。
目标工程的测试仍应使用它实际需要的插件和解释器。

本项目没有修改车辆工程现有的两份通用文档。通用代码规范在独立项目中保留一份，
结构规则重新整理；工程专属规则仍归各业务项目所有。
