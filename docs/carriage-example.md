# 车辆工程接入示例

这是 [moving_carriage_sensors](https://github.com/luyunhong12/moving_carriage_sensors) 的专用接入示例。只有运行车辆构建和仿真才需要相应的 ROS Jazzy、Gazebo 和业务依赖；其他项目可以从[配置手册](configuration.md)开始。

以下命令均在 Supervisor 仓库根目录运行。将车辆工程路径替换为实际位置：

```bash
vehicle_root=/absolute/path/to/moving_carriage_sensors
.venv/bin/supervisor check "$vehicle_root" \
  --config profiles/moving-carriage.toml --output .generated/carriage-readonly
```

要运行构建或制动检查，先准备新副本，再在副本中运行。下面两次检查共用这个副本，依次执行：

```bash
audit_parent=$(mktemp -d)
.venv/bin/python scripts/prepare_carriage.py "$vehicle_root" "$audit_parent/audit"
workspace="$audit_parent/audit/workspace"
.venv/bin/supervisor check "$workspace" --profile full --run-commands \
  --output .generated/carriage-code
.venv/bin/supervisor check "$workspace" --config "$workspace/supervisor-brake.toml" \
  --profile deep --run-commands --output .generated/carriage-brake
```

独立制动测试通过只说明该工况通过。要接入车辆项目自己的整组物理验收，可在准备新副本时选用 `--suite baseline` 或 `--suite experimental`；具体参数见 `scripts/prepare_carriage.py --help`。这个准备脚本依赖车辆项目的目录布局，不是其他工程的安装步骤。
