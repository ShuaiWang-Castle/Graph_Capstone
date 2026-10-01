# ZR-HFD v1.2：中期代码与证据审核快照

对应 `Graph_Capstone/zrhfd_v12_review/`。项目仍ACTIVE，本次不是M0–M6最终交付，也不是已确认改进。旧contraction与全图重叠社区项目仍保留在仓库其他目录。

**当前结论：开发集收益未通过独立验证。** ZR-HFD dev平均F1=.983286，test=.684915；作者HFD test=.898986。总体中位F1=1掩盖严重失败尾部。G-E2 FAIL；G-E1、G-E3亦FAIL，一般超图域G-E0 FAIL；G-E4 NOT RUN。不能声称同质量加速，也不能由不同图分布的落差直接证明过拟合。

## 审核入口

先读 [完整审核prompt](GPT_PRO_ANALYSIS_PROMPT_ZH.md)、[执行报告](REPORT.md)、[理论请求与反例](THEORY_REQUESTS.md)、[冻结规格](provenance/goal-objective.md)、[实验协议](EXPERIMENT_PROTOCOL_ZH.md)。主表在 `results/m4/{dev,test}_main_v12_002/quality_cost_summary.csv`；逐查询CSV保留全部方法及oracle参考。`reviews/m4_analysis/actual_test_v001/G_E2_independent_recheck.json`是实际关卡复核。

dev为24SBM+4附件LFR，共336查询；test为36新校准LFR，共432查询。dev4032/test5184/dev消融1008全部完成并独审。336配对的区域预登记保持R-supp。审计PASS只说明记录/计算一致，科学关卡仍FAIL。

## 公开范围

上传工程核心源码、冻结源/协议、全部普通图逐查询表、消融配对表、失败/理论请求、主图和独审记录。紧凑证据包包含普通图冻结合成图/真值、全部10224项最终cover及来源/配置/时钟、原始文件SHA。冗长native stdout、重复证书中间集合等按缩减清单保留身份；提取文件是派生view，不冒充完整raw。

大规模图、完整M6向量/checkpoint、历史原始树、环境、第三方论文和未许可作者源码不全部上传。原测量本地保留，失败不删除。公开包可进行普通图cover分数重放及源码审查，不能单独复核全部原始solver witness、native内部轨迹或大规模原始审计。实际内容/字节SHA/缩减范围以 `PUBLICATION_MANIFEST.json`、包内manifest及replay receipt为准。projection还缩减了touched/order/sweep中间列表、结构化native metadata和部分trace容器，逐record的removed_fields记录字段/序列化SHA/字节数；完整最终vertices与主要质量/成本字段保留。

## 普通图分数离线重放

在本目录执行（Python3.11+标准库，无需运行算法）：

```bash
python3 reviews/publication/replay_review_covers_v001.py --archive COMPACT_EVIDENCE.zip --publication-manifest PUBLICATION_MANIFEST.json --output new_replay_receipt.json
```

输出路径必须是新文件。复核全部10224个任务的F1/P/R、集合规模、cut、volume、精确Z、conductance及seed-membership元数据，并核验固定分母/任务集合与输入哈希。它不复核完整native/solver witness，不运行新算法、不做test机制诊断或新bootstrap。

实际收据 `reviews/publication/actual_cover_replay_v002.json` 为10224任务/0差异的PASS。它绑定当时的e561f545开头publication manifest，原件保留为 `reviews/publication/actual_cover_replay_input_manifest_v002.json`。之后只增补24份首查询原raw样本、审核文档及收据；archive、固定cohort与三份任务manifest均未变。最终PUBLICATION_MANIFEST是增补后的发布清单，其SHA不冒充此前重放的输入SHA。

M5官方11480项尚NOT RUN；smoke不当正式结果。dev336详细诊断控制器已返回，汇总/独审状态见REPORT；G-E2 FAIL使test432详细机制诊断NOT RUN，不能用本轮test挑选参数。

## 运行与来源

`zrhfd/`是工程核心，`experiments/`含构建、下载、生成、运行和分析，`tests/`含有限核验。HFD/p-norm作者代码按固定commit另取，不随包分发无许可证源码/二进制。LFR MIT生成器也经下载/构建流程获取。准确source/dependency/hash及限制见provenance和协议。

仓库原有MIT License适用于原创项目代码；用户规格/参考与第三方软件保留各自身份，见THIRD_PARTY_NOTICES及source-scope review。既有fresh安装/smoke/恢复的有限PASS不等于完整fresh M0–M6科学重跑PASS。本快照无平台二进制/全局环境/凭据。
