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
`required` 为每种模式分别指定，不隐式继承；缺失、未执行或不适用的必需项让本次退出2。
未列为必需项的检查仍可按源码语言正常报告不适用。

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
`settings.security.timeout` 控制 Bandit 运行时限，默认 120 秒。
漏洞报告须与清单中的规范化包名、版本及数量一致，并包含完整漏洞结果；
合法包名别名、等价版本及报告顺序不影响匹配。缺项、跳过或退出码与报告矛盾时
判为执行错误，不能当作无漏洞。


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
# 可选：自定义 executable 必须通过 --run-commands 授权。
# executable = "/absolute/path/to/doxygen"
```

`clang-tidy` 遵守扫描范围与 `settings.clang-tidy.files`，诊断使用项目相对路径。
只选源文件时仅分析对应编译单元；选中头文件时分析副本内的编译单元，
并用 Clang 包含记录确认所选头文件实际被包含，未包含时报执行错误。
构建依赖可以保留在 `inputs` 中，但范围外诊断不会作为自有代码问题输出；
构建或解析失败仍会报错。编译数据库逐条执行；同一文件的多套编译命令分别保留证据，
相对目录以副本为基准，相对诊断和包含路径以该条编译命令的工作目录为基准。
头文件诊断先采集再按精确路径过滤。日志保留原始副本路径供复核。

`cpp-sanitizers` 默认 address,undefined；`cpp-thread` 独立使用 thread。
变异预算限制的是有效编译并执行的数量；剩余候选会报告预算未完成。
不能通过降低预算宣称变异检查全部通过。

CTest 的 JUnit 失败/错误节点必须与退出码一致；退出 0 却含失败节点，或退出 8
却没有失败/错误节点，均判为执行错误。正常用例失败在允许失败结果的检查器中
保留为 fail；空测试与跳过项仍不能通过。

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

## JSON/XML参数说明

JSON必须通过`settings.parameter-docs.documentation`显式关联逐参数Markdown表格；XML/SDF/URDF/Xacro/world/launch默认读取文件内标准注释，旧参数表可补充缺失说明；YAML继续读取紧邻注释。

```toml
[settings.parameter-docs]
paths = ["config"]
[settings.parameter-docs.documentation]
"config/settings.json" = "docs/settings-parameters.md"
```

Markdown使用两列：`参数路径 | 中文说明`。JSON路径采用JSON Pointer，如`/parts/*/mass_kg`；数组标量由所属键说明。
XML枚举元素与每个属性，例如`/gui[0]/plugin[0]/@filename`；方括号为同名兄弟零基序号。
`*`只匹配一个非空路径段。容器说明不能代替子字段，未使用、重复或重叠路径规则会报错。
JSON记录定位到文件首行，XML保存实际元素行号。重复JSON键、XML DTD和外部实体拒绝解析。
文档内容也计入报告SHA256并检查扫描期间是否变化。机器只验证逐参数存在中文说明，单位、范围和真实性仍需结合业务审查。


### XML 内联注释与纯配置工程

注释排版及属性关联规则见 [代码规范第9节](coding-standard.md#9-参数说明统一规则)。
以下配置可以单独检查仿真文件，不要求同时存在 Python/C++ 源码：

```toml
version = 1
source = ["models"]
checks = ["parameter-docs"]

[settings.parameter-docs]
paths = ["models"]
```

目录识别 `.xml/.sdf/.urdf/.xacro/.world/.launch`；只按 XML 文本解析，
不会执行 Xacro 宏、ROS launch 或外部实体。`.launch.py` 按 Python 检查。
空扫描与无法解析的配置不能通过。TOML/INI 仍会明确报告未实现。

### 历史对比

`compare` 同时核对参数检查实际扫描的配置文件清单；删除、移动或新增配置文件
均视为范围变化，旧报告缺少清单时也不能确认问题已解决。清单顺序变化不影响比较。

`compare` 的 `resolved` 只包含同项目根目录、同范围、同配置且对应检查完成后
消失的诊断。双方还必须明确具有有效快照；缺少身份/快照元信息的旧报告、不同
工作树或迁移后的根目录，以及检查移除、未完成或范围变化，均保守归入 `unverified`。
重复诊断保留出现次数，优先匹配原行号，再配对移动的行号；缺少定义级标识的
同类诊断只能确认数量变化，具体哪个对象被修复仍需人工核对。
`statuses` 继续记录被移除的检查（after 为 null）。

本仓库自身的 deep 配置使用真实的 `mutator` 检查器，明确列出全部 15 个
`src/code_supervisor` 模块和 2 个 Python 维护脚本。测试会核对该清单，新增模块
未加入时会失败。示例、测试代码和 shell 安装器通过测试套件验证，不属于 Python
变异目标；`__init__.py` 当前没有可变异算子。full 模式不会自动执行这一耗时检查。
init 模板只要求已提示配置的 tests；启用变异检查时须同时配置检查器、输入副本和
required.deep。

当前自身变异预算为 2000；`pytest_args` 的 `-x` 仅在单个变异已触发失败后停止
该次测试，正常基线仍运行完整套件。测试排序优先执行规则用例，再运行真实工具链
集成用例；没有过滤用例，也不把预算不足计为通过。

覆盖判定使用 coverage 的语句行号映射，兼容多行表达式，但不借用外层 try/if 的
执行记录代替分支语句。每个变异完成后写入 `mutator/mutator.json`，包含稳定的
`mutation_id`、位置、改动和执行结果，可在长任务中读取进度；中途文件不是完整
检查报告。存活、未覆盖、预算不足和基础设施错误仍保留原始分类；等价变异通过
人工审查说明，不从统计中删除，也不自动改成通过。


隔离副本与源码扫描共享缓存/生成目录排除规则，复制前剪枝，避免读取旧构建和
虚拟环境链接。vendor 不参与自有源码扫描，但作为可能的构建依赖保留在显式输入
副本中。使用 `inputs = ["."]` 时，仍应将 `--output` 设在工程之外；输出目录不能
包含在待复制输入内。普通源码链接仍然拒绝。Ruff 使用隔离解释器加载已安装工具，
目标工程和 PYTHONPATH 中的同名模块不会被当成检查器执行。
