# 紧凑公开检查点构建与 cover 重放：源码独立审查 v001

审查结论：构建脚本的原测量只读边界与 source27 保留机制可接受。初读旧重放版本的完整分母/成员身份问题已通知 root，并在后文记录其增量修正；只读审查不替代实际 payload 成员、归档字节或 cover 数值验收。生产/发布脚本未由本代理修改。

## 受审源码与执行范围

- `reviews/publication/build_review_checkpoint_v001.py`：10711 字节、117 行，SHA-256 `aabf60385bb2208335a01c86e020949bfa028ca644d8c7c6e50869722f0378fe`。
- `reviews/publication/replay_review_covers_v001.py`：3787 字节、46 行，SHA-256 `d1487f59b335e5d2d5577f78cae926d19288f76abd1b6b01cca4015405f9c426`。
- 本代理仅阅读上述脚本及必要的图格式、worker/既有审计、生成和公开说明源码；另由子审查者独立只读复核 replay。没有导入脚本、运行算法/fixture、读取 actual raw/图/ZIP、复制 payload 或执行发布。这里只写本审查文档。
- 当前 v002 构建/重放的实际成功或失败，以 root 另行生成的 receipt 为准。若 root 后续修订源码，本结论绑定上述旧 SHA，不能自动转为新版本验收。

## 构建代码的实际作用

1. `OUT` 固定为新的 `reviews/publication/payload_v002`，已经存在则拒绝；可用空间不足则拒绝。原 source、CSV、raw 与输入仅用读取/复制操作，写路径为 `OUT` 子树、其新 ZIP、PUBLICATION_MANIFEST。未调用 worker、求解器、summary/bootstrap 或算法，也不重写原计时、配置、标签或 cover。
2. 固定三个普通 cohort：dev main 4032、test main 5184、dev ablations 1008，总计 10224。每张 CSV 必须达到相应行数且全部 `COMPLETED`，否则拒绝。以 CSV 的 `raw_path` 逐行读取既有 raw，保存原路径、原文件字节数/SHA 及投影内容；输入图/真值/query 的实际 bytes 必须符合 raw 中的 SHA。
3. 在复制前要求冻结 receipt 的 27 个 source 路径均在 selection 中、当前 SHA 全部匹配。该检查约束 measurement source 保留；其余工程、分析、历史辅助源码不能冒称属于 source27 freeze。
4. 对生成的 ZIP 逐 member 回读并检字节数/SHA；输出 projection_counts、原文件 identity 表、缩减 member 清单和公开 payload hashes。这是构建自身内容的闭合机制，不是重新执行算法，也不等于独立核验全部原 raw-tree。

构建范围限制：代码检查的是 CSV 长度和 status，未自行将 CSV/raw 的 task 与冻结 manifest 全部 job 集合逐项对应，也未拒绝重复 `raw_path`/task 或检查 raw 自身 status 与 CSV 一致。已有 actual audit 可提供外部基础，但构建脚本单独不能证明 10224 个唯一、正确的固定任务。`essential` 变量未被使用，不是一项实际执行的保留字段断言。

## 投影与明确遗漏

`reduce()` 递归保留未命中缩减键的原值；最终 `result.vertices` 等 cover 字段没有被替换或重新选取。以下键在任意深度整项省略：`oracle_trace`、`hull_vertices`、`stdout`、`stdout_preview`、`stdout_excerpt`、`dual_heights`、`scores`、`x`、`heights`、`score_vector`、`height_vector`。每个被删字段记录路径、重新规范序列化后的 SHA/字节数及 item 数；它不是原文件对应 byte slice 的 SHA。原压缩文件 bytes/hash 另行保存。

因此投影保留 final covers 与剩余 metadata，但不能用字段 SHA 重构省略原值；缺失 stdout/dual vector/证书中间 hull/cut oracle 内容也不能从这份公开 ZIP 完整复核 native 内部轨迹、solver stationarity 或原证书所有 witness。所有剩余 cover/metadata 未修改这一源码观察不等于实际 payload 所有成员已经验收。

## 第三方和源码边界

- 源码 selection 从本项目 `zrhfd/`、`tests/`、`experiments/` 的 `.py/.cpp/.jl/.yaml/.sh` 以及少量本项目下载脚本取得；不遍历 `external/hfd/`、`external/pnormflowdiffusion/`、runtime/depot 或论文目录。原 source snapshot 仅选择 ordinary receipt 元数据，不选择其作者源码 bytes。源码扩展选择没有包含 native binary/共享库/PDF。
- CCFA 副本本版明确携 `licenses/CCFA-Skills-MIT.txt`、`provenance/plot-helper.json` 和 helper，且选中代码引用 helper 时要求副本/许可同时存在。当前源 helper 的实际 SHA 为 `242d49c21cd31a6cdcad17e45a322d0cb30e3b57620259c193ef28993100ff66`，与 pin 一致；被选原 MIT 实际 SHA 为 `1ac138d752fc345d61c5790df57caed3487e4d66d59879d6bd60272765d087d2`。这修正 v001 缺 license 的失败，不改写该失败历史。
- `THIRD_PARTY_NOTICES.md` 和作者获取 JSON 是许可/来源 metadata，不授权再分发缺 LICENSE 的 HFD/pNorm 作者代码或 binary。目录排除必须在最终候选任何深层路径保持，不能只凭公开 manifest 的 `excluded` 自报文字判定许可扫描 PASS。
- 当前源码路径观察中，项目 `.jl/.cpp` 只有 thin native driver 和 first-party mincut；并未对实际 payload/ZIP 或全部 Python 内容做全量版权扫描。`experiments/m0_reference/core.py` 明示附件重构 shim，不能冒称旧作者 missing core；历史 helper 也不能冒称本轮 frozen measurement。目标仓库原 MIT 由 root 保留，上游 MIT/GPL/NC-SA 身份保持独立。

## 受审 replay 的阻断与最小修正

**P1：固定 cohort/task 分母缺失（22–39、42 行）。** `projection_counts` 完全取自归档自报值，没有要求恰好上述三个 cohort/数量、task 唯一或原 identity 集合同一。空 `members` 与空 `projection_counts` 会零迭代仍写 `PASS_PRIMARY_COVER_REPLAY`，scope 却声称 all ordinary final covers。这是源码路径上的反例，没有实际运行人工数据。实际重放前应绑定固定三 cohort/10224 分母、唯一 task/原路径与 identity 对照，拒绝缺项/重复/额外项。

**P1：实际读取 cover/input 未要求属于已验成员（11–13、23–25 行）。** 脚本只验证 `manifest['members']`；之后读取的 cover JSONL、graph、truth 路径未要求在该清单中出现一次，也没有将原文件 identity 和 input SHA 对应到其已验 bytes。应先构建唯一已验证 member 索引，再要求每个实际读取路径/身份由该索引和固定任务表绑定。否则只能描述自报 subset 的重算，不能声称归档全部实际读取输入均通过身份检查。

**P2：seed bool 与所有方法必须含 seed 混淆（37 行）。** 既有 ordinary actual audit 比较 `output_contains_seed` 与真实 membership；部分 baseline 的 sweep 参数允许不强制 seed。本版却把任何 `seed not in S` 一律当重放失败。应比较保存的 primary bool 与独立 membership；若某特定方法有额外 seed 约束，应依据冻结 method/config 独立区分。未读取实际 cover，故不宣称本轮一定已有该情形。

其他准确限制：对合法简单无向、无权输入，P/R/F1、size、cut、volume、Fraction Z、phi 公式与生产主质量口径相符；该 parser 不支持生产 Graph 的一般带权/平行边能力，必须限定为当前冻结简单无权 ordinary 输入。volume 为零时没有检查保存 `Z_exact` 必须为空，需维持主字段空值一致性。列表转 set 也未独立拒重复/非法 node；不能据此增称结构全面审计。

replay 只从归档读取、拒绝已有输出并写新 receipt；默认不运行原算法、不调参。其重算范围是 final cover 的 F1/P/R/size/cut/volume/Z/phi/seed membership 与归档成员完整性。它没有独立重算 components、hull F1/全部 certificate、touched/output、原时间/RSS、成本配对或 bootstrap，更不重放 M6；scope 和公开说明应明确这些限制，不能把已经包含的原 telemetry 等同于已独立复核。

待 root 集中修正后可做新 SHA 的只读 delta review；实际 ZIP/cover 重放由 root 独立执行和留收据，本记录不据此扩大为全 raw 审计 PASS。

## v003 构建与重放增量（仍为源码静态审查）

新的 builder 为 12275 字节、145 行，SHA `fd4b61760b8890f3cf30899011648e1d71bf5b315f4c9c1dab01fcea714a6a90`，独占输出改为 `payload_v003`；其原件只读/source27/原 SHA 与输入 SHA 门保留。失败派生归档的保留/清理由 root 另留实际 receipt，本代理未触及原件或这些派生文件。

新 `compact()` 不再宣称完整原 metadata：除前述缩减外，只保留 result 中指定的 `vertices`、`S0`、`region_vertices`、`hull_best`、`mass_sequence` 容器、config/stats、缩减 certificate、trace 的标量及 `vertices`。metadata 仅保留标量和小于 2048 字符文本；其全部结构值、长文本以及其他未选 result 容器（包括 touched 列表）被省略。各删项仍记录规范序列化 SHA/字节数/item 数。顶层原记录字段原值保留，final cover 原值保留；完整 native trial、来源细节对象/大数组、touched 与中间向量不能据投影重新审计。README/receipt 应按实际 removed_fields 理解“记录 metadata”，不能将它等同全部 metadata 原件。

重放增量 `d9d51abbb203dbd84acc960fbf4599d1c44d0c49e8ce911d014e107e3470cf7d`（5609 字节、65 行）已静态关闭旧零条 PASS、固定三 cohort/分母、重复 member/task、cover 与 input 未验证成员及 seed 必须为真问题：外 publication manifest 必须绑定 archive bytes/SHA 和固定 counts，内 manifest 复核固定 counts，cover/input 路径均进入已验 member 索引，input SHA 匹配，完成状态明确，seed 改为原 metadata 与重算 bool 比较。

随后观察到 `4d53e5b722918b75491e52fa5cc7a7fdb4adbfaa0330aca4addf9f68122f1085`（75 行）增加 10224 项 original identity 表的唯一/分母检查及旁置 frozen manifest 的 task 集合比对，逐 record 对照 original path/bytes/SHA。此方向进一步约束完整任务身份；但该版本读取 original identity 表之前未要求它属于已验证 member，旁置 manifest 也未按 publication payload SHA 核验。另 volume 为零时 Z_exact 空值对称检查仍未关闭。以上均已通知 root，可最小修正，不应把“路径存在”当成“内容已由重放验证”。

上述均为明确 SHA 的静态增量观察；没有重放 actual ZIP、没有在本代理审查内运行数值或人工反例。最终 accepted 源 SHA 和实际 PASS 需后续追加，不回填旧版 PASS，也不扩大为全 raw 审计。


## 最终源码收口（本节覆盖前述版本的未关闭状态）

最终静态结论：`ACCEPT_STATIC_PREPARATION_WITH_LIMITATIONS`。最终 replay 已实际读取确认 7056 字节、79 行，SHA-256 `145546d7ffa4cdee249bd9c8f9b837e906f204ade3c8dc0863619311870fce27`；builder 仍为 `fd4b61760b8890f3cf30899011648e1d71bf5b315f4c9c1dab01fcea714a6a90`。没有导入脚本、运行 fixture/数值或读取 actual archive。

三项最后修正已关闭：读取 ORIGINAL_FILE_IDENTITIES 前必须属于已验证 member，10224 唯一 identity 与 projected task/original path/bytes/SHA 对照；旁置三个 frozen manifest 必须与 publication payload 对应路径的 bytes/SHA 一致，再用固定数量 task 集合检查每条 projected record；Z_exact 加 None 对称检查，零 volume 不再允许非空 Z。seed metadata 与重算 membership 的 bool 比较保持，不强求所有 baseline 含 seed。固定三 cohort/counts、unique member/task、COMPLETED 和 cover/graph/truth/query SHA 门均保留。旧 SHA 问题不补 PASS，以此最终 SHA 的收口为准。

只读修正不改变原算法、cover、measurement source/config 或成本。重放限定当前简单无权 ordinary 图，不逐字段重建原 query/job/request/worker 全过程，也不复核被省略的 solver witness/native 内部轨迹、components、hull、touched、原时间/RSS、bootstrap 或 M6。完整原 cohort/查询规范与科学执行过程仍由已有 actual audit 和原件证据承担；不能称全 raw-tree 独立审计。

root 的实际执行报告为 actual_cover_replay_v002.json PASS：全部 10224 项、unique task、0 errors，用时 4.3092 秒；25,266,123 字节 archive 已完整 memberverify。此处明确来源为 root 执行报告，本代理未复跑或读取该 archive/raw。实际收据和 PUBLICATION_MANIFEST 提供其完整 hashes；这个主 cover 分数重算 PASS 不等于原算法复跑、solver 证明或科学关卡 PASS。

最终追加先遇到 ENOSPC，两次失败后确认旧 10557 字节文档及 SHA fbf26aca…完整、没有部分追加；root 释放其自建未测量 cache 后才完成本节落盘。原 production/measurements 未由本代理改变。
