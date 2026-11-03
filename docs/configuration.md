# 配置手册

基本配置为 TOML，未知字段、重复检查名和越界路径会报错。

```toml
version = 1
name = "example"
source = ["src", "tests"]
exclude = []
policy = ["docs/coding.md"]
checks = ["python-docs", "black", "ruff", "pyright", "crapper", "dryer", "mutator"]

[required]
full = ["pyright", "crapper", "dryer"]
deep = ["pyright", "crapper", "dryer", "mutator"]

[settings.pyright]
files = ["src/calculator.py"]

[settings.crapper]
files = ["src/calculator.py"]
inputs = ["src", "tests"]
pytest_args = ["tests", "-q"]
threshold = 10

[settings.mutator]
files = ["src/calculator.py"]
inputs = ["src", "tests"]
pytest_args = ["tests", "-q"]
max_mutants = 100
mutant_timeout = 30

[settings.dryer]
threshold = 0.8
min_lines = 4
min_nodes = 20
```

`files` 是扫描范围中的精确相对文件名，不是 glob；默认取适用语言的全部文件。
`source/exclude` 控制发现范围；默认剪去 .git/.venv/build/install/log/.generated/.tools/vendor。
未跟踪文件也会检查。`policy` 记录规范哈希，不会自动把任意自然语言规范转换成静态规则。
每项 `settings` 可指定 `profile = "quick"|"full"|"deep"` 和 `timeout`（秒）。
`required` 为每种模式分别指定，不隐式继承；缺失项让本次退出2。

## 类型、安全和边界

```toml
[settings.pyright]
config = "pyrightconfig.json"

[settings.dependencies]
module_roots = ["src"]
forbidden = [{from = "domain", to = "web"}]
include_forbidden = [{from = "src/core/", to = "ui/"}]

[settings.security]
files = ["src/calculator.py"]

[settings.secrets]
paths = ["src", "config", ".github"]
max_bytes = 1048576

[settings.vulnerabilities]
requirements = "requirements-locked.txt"
timeout = 120
```

把需要的 ID 加入 `checks` 后才执行。依赖清单要求纯 `name==version` 行，包含全部传递依赖；
不执行 pip 安装/解析脚本。超大凭据扫描文件被记录为未完成，不默默省略。
安全检测通常应选生产源码；测试中的断言可能被 Bandit 报告。

## C++

```toml
[settings.cpp-build]
inputs = ["CMakeLists.txt", "src", "include", "tests"]
cmake_source = "."
configure_args = ["-DBUILD_TESTING=ON"]
jobs = 2
timeout = 180
```

`clang-tidy`、`cpp-coverage`、`cpp-sanitizers`、`cpp-thread`、`cpp-mutation` 各自配置
`inputs/cmake_source/configure_args/jobs/timeout`；各用新副本，避免不同插桩构建串用。
配置不能关闭覆盖率/Sanitizer 所需编译选项；若工程强制覆盖 CMake flags，必须人工核对日志。

```toml
[settings.cpp-coverage]
inputs = ["CMakeLists.txt", "src", "include", "tests"]
files = ["include/calculator.hh"]
minimum = 90

[settings.cpp-mutation]
inputs = ["CMakeLists.txt", "src", "include", "tests"]
files = ["include/calculator.hh"]
max_mutants = 100

[settings.cpp-complexity]
threshold = 10

[settings.cpp-duplicates]
min_lines = 5
min_tokens = 50

[settings.doxygen]
# 可选：executable = "/absolute/path/to/doxygen"
```

`cpp-sanitizers` 默认 address,undefined；`cpp-thread` 独立使用 thread。
变异预算限制的是有效编译并执行的数量；剩余候选会报告预算未完成。
不能通过降低预算宣称变异检查全部通过。

## 业务、性质和性能验收

```toml
[settings.acceptance]
inputs = ["src", "tests", "accept.py"]
argv = ["{python}", "accept.py", "{report}"]
report = "acceptance.json"
timeout = 300
limits = {duration_seconds = 2.0}
```

脚本在隔离目录执行，将本轮结果写到参数指定路径：

```json
{"checks":{"stopping_distance":true,"released_after_reset":true},"metrics":{"duration_seconds":1.25}}
```

checks 必须是非空布尔映射，指标须为有限数；指标超限/判据为假则失败。
旧报告、缺报告、非零退出却全真均不能通过。
`{python}`、`{workspace}`、`{report}` 只替换完整 argv 元素，不做 shell 字符串插值。
性能和物理预期由项目提供，不能由督导工具猜测。

## 自定义命令

```toml
[[commands]]
id = "project-tests"
argv = ["/path/project/.venv/bin/python", "-m", "pytest", "-q"]
profile = "full"
timeout = 120
finding_codes = [1]
```

命令直接在目标根目录执行，保留命令、退出码、耗时和日志。
与专用适配器不同，它只理解退出码，不验证测试数或报告协议；若工具退出0但只跳过全部测试，
不能据此证明行为通过。重要验收优先使用专用适配器或 acceptance。

## 每个参数必须有中文说明

在checks中加入`parameter-docs`，并明确列出实际配置目录：

```toml
[settings.parameter-docs]
paths = ["src/example/config"]
```

该检查默认quick执行，同时检查扫描范围内全部Python/C++函数具名参数。
paths为空列表表示明确只检查函数，不能宣称已检查配置；不填写paths则报错。
Python按Args逐名核对，C++按@param逐名核对；YAML按映射键核对同层紧邻或同行注释。
文件头不能代替后续键的说明，流式映射的子键不能借用容器说明。
源码语法错误、C++宏解析不完整、其他未支持配置格式、配置检查中变化均报告错误。
函数参数注释规则不会自动验证物理单位及描述真实性，须结合24项清单审查。
