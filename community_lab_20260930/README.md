# 全图重叠社区检测：2026-09-30 实验与负面结果

最终状态：**NO_REPRODUCIBLE_GAIN（未通过事先冻结的准入）**。本目录是独立的、结果优先的实验快照；仓库原有安全收缩研究保留在原位置，本轮没有继续那些路线。

普通无向无权图、拓扑输入，24张LFR开发图，CPU串行并设置1线程。576项正式任务中564项完成并评分，12项BigCLAM原生估K任务超时且质量未知。比较BigCLAM、NOCD-G、Ego-splitting、Highway和SLPA；已知K与原生估K、不同语言实现分别呈现。确认图没有生成或使用。

## 实际卡点

1. **局部计算加速没有成为跨规模的同质量改进。** NOCD的CSR采样点积在5000节点图上，三个算法种子的完整流程中位节时为18.48%、17.15%、17.45%，36对更新次数全部相同。但1000节点图慢7.3%–7.9%；seed75平均macro F1差为−0.0108144，低于预先冻结的−0.01门槛。小图5个case/seed出现至少0.03的macro或micro退化，不能只归结为平均值略微越界。
2. **时间收益有直接profile证据，质量漂移的具体因果环节尚未定位。** CSR减少大图gather/scatter开销，但unique、排序、CSR和inverse准备在小图不划算。相同初始化和数学等价没有排除浮点顺序引起的训练轨迹差异；目前没有证据把全部质量退化唯一归因于某一个算子或停止时刻。
3. **训练目标与归属恢复有差距，增加预算效果有限。** 9/24原NOCD任务存在某个已保存点的事后macro F1比返回点高至少0.03。真标签只用于离线诊断，不能用它选择checkpoint。将训练上限加倍使大图耗时约1.80–1.89倍，macro改善仍很小且方向不一致；这不是固定墙钟预算实验。
4. **强基线限制了方法层面的贡献。** 已知K面板中，原生C++ BigCLAM在全部12张大图上比原始PyTorch NOCD更快，macro和micro F1也更高。优化NOCD的某个计算后端尚不足以声称推进全部方法的质量—成本前沿。不同实现栈也不能单独证明算法复杂度优势。
5. **其它明显问题已有解释，但不是现成的新研究贡献。** BigCLAM原生估K的12张大图全部在300秒内的CV阶段超时；小图完成子集CV占原生舍入CPU时间的中位94.51%。Ego某实现的内部自环会消除重叠容量，但去自环和更强上游配置是已有修复/控制。它们不能包装成新原理。

一句话insight：**NOCD采样点积的大图访存成本可以降低，但等价计算的数值轨迹和小图准备成本，使局部加速无法自动变成同质量的社区恢复改进。** 这是本轮实验证据支持的工程观察，不是新定理。

## 阅读入口

- [最终报告](reports/FINAL_REPORT_ZH.md)
- [基线报告](reports/BASELINE_REPORT_ZH.md)
- [失败与耗时定位](reports/FAILURE_MAP_ZH.md)
- [候选决定与冻结标准](reports/CANDIDATE_DECISION_ZH.md)
- [576项结果CSV](analysis/results.csv) / [JSON](analysis/results.json)
- [配对结果和准入判定](analysis/nocd_pairdot_gate_v1/)
- [GPT Pro分析prompt](reports/GPT_PRO_ANALYSIS_PROMPT_ZH.md) / [紧凑分析包](reports/GPT_PRO_ANALYSIS_PACK.zip)

## 下载数据并复核评分

[data/compact-replay.zip](data/compact-replay.zip) 含24张实际图、离线评价真标签、576项原spec/result、564个最终cover、3,017项原索引依赖及许可证，另含正式任务stdout/stderr和阶段/profile证据。[校验记录](data/compact-replay.sha256.json)给出实际SHA-256与文件数。所有原记录按字节保留；其中机器路径只作为历史测量元数据，评分器按当前解压目录读取相对路径。

在本目录下执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install numpy==2.5.3 scipy==1.18.1
.venv/bin/python -m zipfile -e data/compact-replay.zip replay_workspace
.venv/bin/python replay_workspace/tools/portable_replay.py verify --root replay_workspace --index replay_workspace/provenance/replay_index.json
.venv/bin/python replay_workspace/tools/portable_replay.py evaluate --root replay_workspace --index replay_workspace/provenance/replay_index.json --output replay_scores_new.json --forbid-original-input-opens
```

完整原依赖版本见[dependency_versions.txt](provenance/dependency_versions.txt)。本轮已经在异地目录实际复算564项核心评分，全部在1e-12容差内一致，12项保留UNKNOWN；该工具不会重新训练、重新测时或重算ONMI。公开压缩包另做CRC及全部索引依赖SHA核验。

## 公开快照的边界

这里公开实验/评价代码、适配器、候选、配置、源版本和补丁、报告、汇总/配对数据、最终cover及评分复核输入。原始模型、embedding、完整保存cover历史和61MB完整源码归档未纳入Git；它们保存在已交付的2.22GB `DELIVERY.zip`，其SHA和原独立验收见[DELIVERY.sha256.json](DELIVERY.sha256.json)及[验收报告](work/setup/final_zip_postcheck_v1/FINAL_ZIP_POSTCHECK_ZH.md)。该验收针对完整本地交付包，不能解释为GitHub含有这些省略产物。

`REPRODUCE.sh`是完整DELIVERY环境的原始新训练入口，依赖省略的 `provenance/locked_source_trees.tar.gz`，**不能仅凭这个公开快照直接完成全量重新训练**。使用完整DELIVERY时按[复现说明](docs/REPRODUCIBILITY_ZH.md)执行。公开快照可直接做上述离线评分复核；不声称已完成另一套全新依赖环境的576项重训练。

历史报告中的其他相对证据路径可能仅在完整DELIVERY中存在，未因公开裁剪而改写原报告。源文件与结果的发布清单见 `PUBLICATION_MANIFEST.json`。第三方代码分别保留原许可证，见[THIRD_PARTY.md](THIRD_PARTY.md)。
