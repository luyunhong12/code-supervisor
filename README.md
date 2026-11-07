# Code Supervisor · 代码督导队

Code Supervisor 是一个给 Python 和 C++ 工程做代码审查的命令行工具。工具装一份，每个工程用自己的 `supervisor.toml` 指定要查的代码、规则和测试。你可以直接在终端运行，拿到中文报告；整个检查过程不需要 AI 或模型密钥。

## 为什么我用 Markdown

我做这个项目，是因为我自己不习惯通过 Skill 管理代码审查规则。我更习惯打开一份 Markdown：看到某条规则不适合自己的工程，就能直接改；想请另一个 AI 帮忙，也只需要让它读同一份文件。

因此，我把怎么审查、哪些地方需要人判断写进了 [AI_REVIEW.md](AI_REVIEW.md)，把可以重复执行的检查交给命令行。比如，工具能找出两段相似的代码，但它们是否表达同一条业务规则、将来是否应该一起改，仍然要结合代码判断。

## 第一次运行

下面以 Linux 为例。在 Ubuntu 24.04 上，请先准备 Git、Python 3.12（含 venv）、Node.js、npm、CMake/CTest、GCC/G++（含 gcov）和 Doxygen，并确保可以联网。安装脚本最后会检查完整工具链，即使只运行 Python 示例也需要这些工具。

```bash
sudo apt-get install git python3-venv nodejs npm cmake g++ doxygen
```

```bash
git clone https://github.com/luyunhong12/code-supervisor.git
cd code-supervisor
bash scripts/bootstrap.sh
.venv/bin/supervisor check examples/python-demo
```

最后一条命令会按[示例配置](examples/python-demo/supervisor.toml)做快速检查。打开本次输出目录里的 **report.txt**，先看哪些项执行了，再看发现的问题。退出码 0 表示本次选定的检查通过，1 表示发现问题，2 表示执行出错或必需项未完成。需要程序读取或对比两次结果时，使用同目录下的 report.json。

## 在自己的工程里使用

在 Supervisor 仓库目录执行下面两步，将路径换成目标工程的实际路径：

```bash
.venv/bin/supervisor init /path/to/your-project
# 打开目标工程新生成的 supervisor.toml，填好源码范围、测试入口及必需检查。
.venv/bin/supervisor check /path/to/your-project --profile full --run-commands
```

日常修改可以先用默认的 quick 模式；需要测试和构建时用 full；配置了变异测试等耗时检查时再用 deep。各模式只执行配置选定的检查。使用 `--run-commands` 前请读一遍项目配置：自定义命令可以在目标工程里执行，隔离构建目录不能代替安全沙箱。

请 AI 协助时，可以直接说：

> 请先读 Code Supervisor 仓库里的 AI_REVIEW.md，再按目标工程的 supervisor.toml 运行检查。把已通过、发现问题和未执行的项目分开说明。结合源码判断哪些问题值得修，这次先不要改代码。

## 参考了谁，项目自己做了什么

- **审查原则**参考 [unclebob/ub-mode](https://github.com/unclebob/ub-mode)，整理成[24 项中文审查清单](docs/review-checklist.md)；工程约定沿用车辆项目的[通用代码规范](docs/coding-standard.md)和[结构与拆分规则](docs/architecture.md)。这份清单既供人阅读，也供 AI 使用；其中需要工程判断的条目没有被算作自动检查通过。
- **Python 质量检查**接入 unclebob 的三个项目：[crapper](https://github.com/unclebob/crapper) 结合复杂度与测试覆盖率识别风险函数，[dryer](https://github.com/unclebob/dryer) 寻找结构相似的代码，[mutator](https://github.com/unclebob/mutator) 提供变异算子，Supervisor 在副本中执行测试，观察测试能否发现改动。实际安装的上游提交见[固定版本清单](requirements-ub.txt)。
- **C++ 使用单独的工具链**：例如用 Doxygen 检查文档、Lizard 计算复杂度、jscpd 寻找重复片段、CMake/CTest 构建并运行测试。具体工具、依赖和适用范围见[能力与限制](docs/capabilities.md)。
- **Supervisor 自己负责**把规则和检测器接到同一个工程配置与命令行上，按项目指定的入口执行检查，记录检查范围、结果和日志。你可以换一个工程继续使用，也可以回头核对某个结论是怎么得出的。

## 按需阅读

| 你想做什么 | 从哪里开始 |
| --- | --- |
| 配置检查范围、函数及配置参数注释、测试与构建 | [配置手册](docs/configuration.md) · [C++ 示例](examples/cpp-demo/supervisor.toml) |
| 看一个 ROS/Gazebo 工程如何接入 | [车辆工程案例](docs/carriage-example.md) |
| 核对实际验证过哪些能力 | [验证记录](VALIDATION.md) |
| 在 GitHub 上自动检查并保存报告 | [CI 工作流](.github/workflows/quality.yml) |

## 许可证

Supervisor 自有代码与文档采用 [MIT 许可证](LICENSE)。中文清单参考 ub-mode，保留原作者声明；各检测器保留各自的许可证。见[第三方来源与授权](THIRD_PARTY_NOTICES.md)。
