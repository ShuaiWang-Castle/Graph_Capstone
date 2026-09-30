# 社区发现：结果驱动的 Goal-Mode 实验室

日期：2026-09-30。本目录已完成真实基线与C1开发实验。主状态 **NO_REPRODUCIBLE_GAIN（未通过冻结准入）**；保留n5000局部开发加速，不宣称独立确认。

## 最终交付入口

- `reports/FINAL_REPORT_ZH.md`：执行范围、结果、瓶颈、未执行项与证据边界。
- `reports/BASELINE_REPORT_ZH.md`、`FAILURE_MAP_ZH.md`、`CANDIDATE_DECISION_ZH.md`：完整基线、实际trace和冻结决定。
- `analysis/results.csv/json`：576计划任务，564完成评分、12 BigCLAM auto-K超时质量未知。
- `docs/REPRODUCIBILITY_ZH.md`：离线迁移复评分和新隔离测量入口；不能重置当前deadline。
- `verification/portable_replay_full_v1/audit.json`：实际不同根目录564核心评分重算一致，12UNKNOWN。
- `verification/source_restore_v2/audit.json`：1,853实际源文件恢复内容/大小/权限一致。
- `DELIVERY.zip` 与 `DELIVERY.sha256.json`：完整最终包及实际SHA/CRC、嵌入replay/source校验结果。

起点2026-09-30T05:02:08.976173+00:00、deadline2026-10-01T05:02:08.976173+00:00从未重置。确认211/212和另一生成器正式图未生成/使用。未自动push，未改打开的论文。

以下基础设施介绍保留原始任务包的历史来历；原包描述“尚未安装/运行”不代表本目录的最终实验状态。原始ZIP及源hash保留，正式结果以raw records、最终报告及验证产物为准。

## 要机器做什么

固定任务为 **普通无向无权图、仅拓扑信息、全图重叠社区检测**。先跑强实现，定位丢失归属的最早阶段或耗时最大的环节，再用最多两个候选机制做单点修改和新种子验证。目标是同质量更快，或同预算更好。不会为了救故事返回名额模型、安全收缩、BCSU、residual fission、恢复阈值或另一条任务。

## 阅读入口

1. `GOAL_MODE_PROMPT_ZH.md`：当前最高优先级任务书，可直接发给 Claude Code / Codex。
2. `docs/EXPERIMENT_PROTOCOL_ZH.md`：数据、指标、信息预算、失败记账、迭代与确认。
3. `docs/BASELINES_AND_SOURCES_ZH.md`：来源、身份、代码问题及要核验的差异。
4. `docs/DELIVERY_CONTRACT_ZH.md`：必须实际交付什么。
5. `context/RESULTS_FIRST_ZH.md`：上一轮地图，只作背景。与本任务书冲突时，以本包为准。

## 原任务包的内容与历史完成范围

已提供并在本会话运行基础检查：
- 图/cover 格式检查；完整标签的一对一社区匹配、micro与重叠/额外归属指标；
- 子进程运行、超时、进程树RSS监测、失败保存、断点续接及配置哈希；
- 原生重叠LFR调用与格式转换接口、固定开发网格；
- 运行计划、完整状态表、质量—费用散点图脚本；
- 作者/公开实现的薄适配器：SNAP BigCLAM、NOCD-G、CDlib SLPA/Highway、Karate Club Ego-splitting；
- 23个离线单元测试；Highway anchor容量机制检查。

**原始任务包制作时没有成功下载、编译并运行这些第三方完整基线，也没有生成24张LFR开发图；本目录当前轮次已全部实际执行，见上方入口。** 原包制作容器当时网络DNS不可用。原生适配器按本轮核对的接口编写，只经过语法检查；其安装、版本锁定、API/device兼容和功能smoke test，是执行机器的第一项工作。接口不匹配可以在留痕后修复，不能把导入错误解释成论文算法失败，也不能停在“需要安装”就交付计划。

只含本次自写基础设施及此前自写机制检查，没有打包第三方论文、第三方源代码、模型权重或私有图。初始 `requirements.txt` 是基础设施兼容范围，不是已冻结的基线环境；宿主应建立隔离环境并输出精确依赖锁。

## 最短启动

在解压目录内：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
bash START_HERE.sh
```

Windows可逐条运行其中的Python命令；正式native性能比较推荐Linux。不要安装或改动用户已有全局环境。

随后由代码Agent按 `GOAL_MODE_PROMPT_ZH.md` 继续执行。**START_HERE不是一键完整benchmark**；它建立运行环境并验证基础设施。实际基线安装需要先阅读来源与许可。

## 后续命令示例

```bash
# 只拉源码，不自动执行安装器；动态refs在宿主记录精确commit。
python tools/fetch_sources.py --only snap lfr nocd cdlib_highway karateclub
# 审核源码及许可后，在相应目录按作者makefile构建；机器负责解决兼容性并留diff。
make -C external/lfr/unweighted_undirected
make -C external/snap/examples/bigclam

# 先smoke并核验所有方法输入输出、实际默认值；再冻结configs。
python tools/generate_lfr.py --binary external/lfr/unweighted_undirected/benchmark
python tools/prepare_plan.py --catalog work/dev_lfr/catalog.json
python tools/run_jobs.py --plan work/plans/baselines.json
python tools/summarize.py --catalog work/dev_lfr/catalog.json \
  --plan work/plans/baselines.json --plot
```

注意：BigCLAM可执行文件名称与LFR输出名称须以实际构建为准。NOCD和Ego的第三方依赖安装不由这些make命令完成。缺源产生BLOCKED行，而不是成功行。补齐之后建立明确的新计划/attempt，不覆盖已记录失败。

## 资源与授权

本包建议一轮24小时墙钟上限、单个测量任务1 CPU线程、测量任务串行；CPU单任务预算1000节点120秒、5000节点300秒。可在已授权机器的空闲GPU上另建GPU面板，最多1块，不租新机器、不调用付费服务。资源限制须先按宿主可用量下调并冻结，不能自动上调。

`session.py`创建不随resume重置的整轮deadline，`run_jobs.py`同时检查它和已记录任务的累计墙钟；安装、分析、手动命令和崩溃前未记录的时间还必须由Agent跟踪。它不是覆盖所有活动的系统级调度器，不能终止本任务之外的进程。

不修改原Graph_Capstone固定43×5实验和负面结论，不自动push远端。原始1.3GB运行树和Claude名额检查脚本不在本包内。
