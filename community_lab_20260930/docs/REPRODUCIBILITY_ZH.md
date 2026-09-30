# 复查与重新运行

当前轮次的状态和唯一deadline见 `work/state.json`；恢复只依据 `RESUME.md` 与已验证的runner PID/create_time，不重新创建轮次。原测量的 plan/spec/result、图/真标签/cover、保存模型与检查点不可改写。

## 离线复评分，不重新训练

最终包内 `provenance/replay_index.json` 用相对路径绑定所有正式结果及原始测量和评价哈希。原记录中的实际绝对路径/命令保留为证据，复评分读取当前解压根目录中的相对文件。它不能制造新的算法耗时，也不把超时转成完成。

将最终 DELIVERY.zip 解压到与原工作区不同的目录，进入该目录，用独立 Python3.12 环境安装记录的 NumPy/SciPy（精确版本在 `provenance/dependency_versions.txt`）。执行：

```bash
python tools/portable_replay.py verify --root . --index provenance/replay_index.json
python tools/portable_replay.py evaluate --root . --index provenance/replay_index.json --output replay_scores_new.json --forbid-original-input-opens
```

上面的 guard 要求不同解压根目录，拒绝打开原位置的 indexed payload；它是可信评分代码的诊断钩子，不是系统安全sandbox。工具逐字段比较核心评分和固定Hungarian匹配，默认绝对容差1e-12。没有完整真标签、没有合法cover或缺输入的行保留质量UNKNOWN。保存的ONMI值/来源hash仅验证，不在该工具中重新计算。

正式 DELIVERY 会包含 index 依赖的精确源码/二进制payload；因此复评分无需网络取得算法源码。所有原训练模型、embedding与实际saved cover仍另行保存；紧凑复评分副本不能代替这些产物。

## 完整新测量

```bash
PYTHON=python3.12 bash REPRODUCE.sh --new-reproduction
PYTHON=python3.12 bash REPRODUCE.sh --new-reproduction --all-development
```

默认重跑九项初始版本与24开发图；第二条另加已有Ego强配置、四个NOCD primitive/cap控制×73/74/75、原作者adapter同轮身份/费用控制。脚本建独立 `replays/` 目录和venv，使用归档实际源码及已锁依赖，强制重编译三项原生目标（Highway为Release/O3，并显式关闭OpenMP以维持本轮串行实现），实际运行原生适配器smoke并保留错误，不修改旧轮次/全局环境，不push。新轮次自己的24小时预算不是旧轮次的续期；这些命令供明确的新复现实验使用。

本轮精确Mac ARM64/Python/库/编译器/线程/RSS测量定义都留在provenance、setup和job metadata。另一平台的新耗时不能冒充旧机结果；源码版本相同不保证不同编译时间/工具链的二进制逐字节一致。源码tar排除git/build对象与第三方论文PDF，保留许可证；公开文章URL、下载时间和SHA另存。

脚本语法检查不等于完整新环境重跑已通过；原生功能smoke、实际当前轮次测量、离线迁移复评分分别报告证据和未完成项。若独立确认阶段实际执行，最终报告及冻结配置将另给确切重跑入口；不能据确认反馈自动重新调参。


## 本轮已经实际验证的范围

`verification/portable_replay_full_v1/audit.json` 记录了异地materialize的3,017个索引依赖文件，564项核心评分RECOMPUTED_MATCH、12项超时QUALITY_UNKNOWN，原位置indexed输入guard启用。不是重新训练，也没有在迁移工具重算ONMI。`verification/source_restore_v2/audit.json`记录实际恢复1,853文件，内容、大小、权限全部相同，归档不含论文PDF。完整fresh依赖环境和全576项重新测量未再次执行，不能由上述通过推断它们已经成功。

正式准入关闭，确认/另生成器正式图未生成，因此没有独立确认重跑命令。新复现脚本不会自动因某组得分好而选择或调参。早期 `verification/BUILD_VERIFICATION.json` 是原任务包制作时的基础设施证据（当时尚未安装native），`provenance/SOURCE_LOCK.json` 的早期执行状态同属历史冻结证据；不要改写它们，也不要把它们当最终执行状态。

实际完整交付ZIP除通用文件SHA/CRC，还逐条核对其中嵌入的replay index依赖SHA/大小和source tar SHA；权限保留。读取最终 `DELIVERY.sha256.json`确认外层ZIP本身的SHA与核验结果。
