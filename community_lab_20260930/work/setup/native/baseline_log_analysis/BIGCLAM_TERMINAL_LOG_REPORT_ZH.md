# BigCLAM 终态日志的实际阶段证据

快照 UTC：2026-09-30T06:41:39.199648+00:00。本轮计划尚在运行；当时共有 202 项终态，其中 BigCLAM 46 项。只读权威 result.json 已终态目录；未读活跃输出、真标签或质量分数，未跑测量、未改冻结源码/配置。

## 状态与阶段

| 方法 | 状态 | 终态项数 |
|---|---|---:|
| bigclam_native | COMPLETED | 12 |
| bigclam_native | TIMEOUT | 12 |
| bigclam_oracleK | COMPLETED | 22 |

TIMEOUT 是预算内未完成，pipeline_seconds 为实际停止花费，不能当完成时间。下面的完成条件统计只描述此快照已完成子集，不能推广到未跑或超时项。

| 方法/n | 完成/终态 | 完成条件 pipeline 中位秒 | timeout 阶段 |
|---|---:|---:|---|
| bigclam_native/1000 | 12/12 | 15.177446 | {} |
| bigclam_native/5000 | 0/12 | NA | {'cv': 12} |
| bigclam_oracleK/1000 | 11/11 | 0.638217 | {} |
| bigclam_oracleK/5000 | 11/11 | 12.428742 | {} |

## 超时的可复放 trace

| job | 最后 K | 已完成 CV MLE | 最后阶段 | 最后更新尝试 | 本次 MLE 整秒 wall | usable checkpoint |
|---|---:|---:|---|---:|---:|---|
| lfr_n5000_o00_m20_s11__bigclam_native__s73 | 253 | 27 | cv | 20000 | 30 | False |
| lfr_n5000_o00_m20_s12__bigclam_native__s73 | 253 | 27 | cv | 25000 | 37 | False |
| lfr_n5000_o00_m50_s11__bigclam_native__s73 | 160 | 24 | cv | 30000 | 57 | False |
| lfr_n5000_o00_m50_s12__bigclam_native__s73 | 160 | 24 | cv | 30000 | 58 | False |
| lfr_n5000_o20_m20_s11__bigclam_native__s73 | 160 | 26 | cv | 40000 | 28 | False |
| lfr_n5000_o20_m20_s12__bigclam_native__s73 | 253 | 27 | cv | 15000 | 23 | False |
| lfr_n5000_o20_m50_s11__bigclam_native__s73 | 160 | 24 | cv | 20000 | 44 | False |
| lfr_n5000_o20_m50_s12__bigclam_native__s73 | 160 | 24 | cv | 30000 | 60 | False |
| lfr_n5000_o40_m20_s11__bigclam_native__s73 | 253 | 27 | cv | 25000 | 43 | False |
| lfr_n5000_o40_m20_s12__bigclam_native__s73 | 253 | 27 | cv | 10000 | 15 | False |
| lfr_n5000_o40_m50_s11__bigclam_native__s73 | 160 | 24 | cv | 20000 | 42 | False |
| lfr_n5000_o40_m50_s12__bigclam_native__s73 | 160 | 24 | cv | 25000 | 52 | False |

## 可支持与不可支持的耗时诊断

- 原生 autoK 已完成子集 12 项；完成 CV 的累计 CPU 时间占原生总 CPU 时间比例中位数 0.945145，范围 [0.896913,0.966667]。各 routine 的时间均已舍入，且是 CPU 时间，非完整 wall 阶段表。
- 超时原生 autoK 共 12 项，逐项上表列出最后观测阶段。训练阶段不保存 F，若无 runner checkpoint 则保留质量未知。
- -nc:10 通常产生11个K格点，每个3次CV MLE。实际尝试网格、接受CLI与每K已完成次数见 JSON/CSV；缺失候选表示未走到该处，不是算法主动舍弃。
- MLE completion、conductance 与 native run time 来自 clock() process CPU。日志进度的 [N sec] 来自 time(NULL)，整秒且每次MLE归零。不能当作外层单调clock的精确阶段wall。
- 串行 iterations 是vertex-update attempts，包含跳过，非实际梯度次数。printed likelihood初始化0且会陈旧，不能从日志中0推质量失败。
- 原生 completion 不给停止理由，不证明global convergence；未完成MLE的duration不插补。
- 完成cover按result身份记录；native cmtyvv语法有效不证明中途文件已完整，本分析未抢救或改变任何状态。
- 未计时的holdout构建、I/O与初始化其他步骤不能通过CPU余额精确归因；完整阶段wall需要另做一致instrumentation的研发profile。

## 后续公平同预算控制（未登记算法候选）

1. 主面板保留原 graph-only autoK 的发现+CV+最终fit+输出完整成本。增加120/300秒预算必须建立独立arm，保留原超时并记录新增预算；不能将超时预算当完成时间。
2. 模型选择政策比较须对双方依同一graph-only可观测输入冻结K网格/评分/终止，不读标签或真实overlap。更少K尝试属于搜索政策与容量变化，需要同样少试验的简单控制。
3. oracle-K只作同信息面板下的最终fit诊断，可展示已知K减去模型选择负担，但不能作为graph-only的免费快捷版或跨面板赢家。
4. BigCLAM内部seed固定10，73/74/75只是重复计时，不是独立随机算法seed。新进程、同binary/hash/线程分别报告计时散布；新增checkpoint或profile应对照两arm一致。
5. 用原生holdout likelihood选最终K，不用offline真质量择候选/epoch；quality-cost仅用真实保存cover/checkpoint，不插值time-to-quality。
6. 没有阶段wall证据之前，不能宣称耗时已精确分摊；本快照仅支持CV MLE的CPU占比与超时所处阶段。

完整逐job轨迹与哈希见 bigclam-terminal-jobs.json；平表见 bigclam-terminal-jobs.csv。可重跑本离线脚本更新同一派生分析文件，原始终态结果与日志不修改。
