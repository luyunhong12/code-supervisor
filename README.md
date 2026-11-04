# 代码督导队 0.2.0

独立安装、多个 Python/C++ 工程共用的代码检查工具。命令行不调用 AI；
AI 工作说明是普通 [AI_REVIEW.md](AI_REVIEW.md)，没有 Skill，也不需要模型密钥。
原 ub-mode 原则整理为 [24项中文督导清单](docs/review-checklist.md)。

## 你实际会怎样用

工具只安装一份，每个工程提供一份 `supervisor.toml`：声明源码、测试、构建输入和规则。
工具读取配置，调用对应检测器，在独立目录保存中文报告。新增工程不复制工具源码。
配置也可以保存在工具的 `profiles` 目录，通过 `--config` 指定。

```bash
/home/yh/Project/code-supervisor/.venv/bin/supervisor check /path/to/project
/home/yh/Project/code-supervisor/.venv/bin/supervisor check /path/to/project --profile full --run-commands
/home/yh/Project/code-supervisor/.venv/bin/supervisor check /path/to/project --profile deep --run-commands
```

- quick：基础文档、格式、静态规则。
- full：配置选定的类型、依赖、安全、复杂度、重复、覆盖率、构建及业务验收。
- deep：另运行配置选定的 Python/C++ 变异与 C++ 运行时检查。

模式只选择**已配置**的检查，不会自动产生测试。需要某检查时用 `required` 声明，缺项不能通过。
详见[配置手册](docs/configuration.md)、[能力与限制](docs/capabilities.md)。

## 获取与更新

独立仓库：[luyunhong12/code-supervisor](https://github.com/luyunhong12/code-supervisor)，
默认分支为 `main`，当前为私有仓库，需要获授权的 GitHub 账号。
源码、中文规范、示例、固定依赖清单和 CI 配置均在仓库中；
不上传 `.venv`、`.tools`、业务工程或本机检查报告。

```bash
git clone https://github.com/luyunhong12/code-supervisor.git
cd code-supervisor
bash scripts/bootstrap.sh
.venv/bin/supervisor init /absolute/path/to/your-project
# 先按目标工程调整 supervisor.toml 中的源码、测试和构建入口。
.venv/bin/supervisor check /absolute/path/to/your-project
```

已有安装更新时，在工作区干净的前提下运行 `git pull --ff-only`，
再运行 `bash scripts/bootstrap.sh` 同步固定依赖。完整和深度检查的命令见下文。

## 安装和验证

当前支持 Linux、Python 3.11+（实测3.12）、Node.js、GCC、CMake/CTest、Doxygen。
Ubuntu 系统依赖由管理员安装：`sudo apt-get install cmake g++ doxygen nodejs npm python3-venv git`。
本项目安装脚本不执行 sudo，也不改业务工程：

```bash
bash scripts/bootstrap.sh
.venv/bin/supervisor doctor
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/supervisor check examples/python-demo --profile deep --run-commands
.venv/bin/supervisor check examples/cpp-demo --profile deep --run-commands
```

脚本联网安装固定版本依赖、原版 ub 三工具的固定提交、jscpd 与 Python 解析器。
`doctor` 只核对工具可发现性；真实检测能力由测试和示例验证。
本机 Doxygen 安装在 `.tools/doxygen`，来源及实测证据见 [VALIDATION.md](VALIDATION.md)。
新机器可以使用系统 Doxygen，不分发本机二进制。工具自身依赖与业务依赖分离；
Python 隔离测试需要的业务包及 pytest 插件仍需在执行环境准备好。

## 新工程接入

```bash
.venv/bin/supervisor init /path/to/project
```

修改生成的配置；测试/构建项目可参考两个 `examples/*/supervisor.toml`。
每项检测必须知道测试入口、构建文件和范围，无法仅凭“检查所有代码”推断正确运行方式。
`inputs` 是复制到本次隔离目录的文件/目录；不能包含输出目录。建议 `--output` 指向工程外。
变异和 CMake 构建在副本执行；普通自定义 `[[commands]]` 则在原工程执行。
`--run-commands` 表示允许可信配置执行项目代码/查询漏洞库，**不是安全沙箱**。
配置可能访问设备、网络或外部路径，使用前须审查。

## 车辆工程

基础只读检查：

```bash
.venv/bin/supervisor check /home/yh/Project/moving_carriage_sensors \
  --config profiles/moving-carriage.toml --output .generated/carriage-readonly
```

创建新副本，再在副本执行构建或仿真：

```bash
.venv/bin/python scripts/prepare_carriage.py /home/yh/Project/moving_carriage_sensors /tmp/carriage-audit
.venv/bin/supervisor check /tmp/carriage-audit/workspace --profile full --run-commands --output .generated/carriage-code
.venv/bin/supervisor check /tmp/carriage-audit/workspace --config /tmp/carriage-audit/workspace/supervisor-brake.toml --profile deep --run-commands --output .generated/carriage-brake
```

创建脚本的 `--suite baseline` 或 `--suite experimental` 选择工程原有物理验收。
其运行需要 ROS Jazzy/Gazebo、完整依赖及足够时间；不会把独立制动测试算作整车仿真通过。
车辆接入脚本只对当前项目布局适用，其他工程直接配置通用适配器。

## 报告与自动化

每次生成唯一目录：`report.txt`、`report.json`、`report.sarif`、检查器证据和日志。
JSON 保留范围、源码/规范/配置 SHA256、Git 状态及各项结果。
退出0：本次选定检查通过；1：发现问题；2：执行错误或选定必需检查未完成。
“不适用”和“不属于本模式”明确记录，不能等同于整项目通过。

```bash
.venv/bin/supervisor compare /path/old/report.json /path/new/report.json
```

比较不自动豁免历史问题；改了范围或配置会提示，删除诊断不等于修复。
GitHub Actions 配置位于 `.github/workflows/quality.yml`，上传报告而非完整源码副本。
本地钩子配置为 `.pre-commit-config.yaml`，安装 pre-commit 后运行 `pre-commit install` 才生效。
工具不会自动提交、推送、发布或发送评论。漏洞查询会联网；凭据扫描不联网验证密钥。
报告和日志可能包含业务数据，分享前需检查。

## AI 与人分别做什么

告诉 AI：“阅读 `/home/yh/Project/code-supervisor/AI_REVIEW.md`，按其中流程审查目标工程。”
AI 阅读规范、运行同一 CLI、解释候选问题，并审查单位、物理假设、职责和契约真实性。
CLI 单独运行也能完成已实现的机器检测；不需要 AI。
两者都不能保证项目完美，覆盖率和变异检出率也不是代码正确率。

## 参数注释检查

新增`parameter-docs`：检查Python/C++函数参数与显式配置范围中的YAML键是否有对应中文说明。车辆基础和副本配置已启用。规则与例外见AI_REVIEW.md，配置方式见docs/configuration.md。
