# ZR-HFD 紧凑 GitHub 检查点：源码发布范围独立审查 v001

结论：本轮可选择发布本项目原创实现、实验控制/分析/测试和构建下载入口；无许可的 HFD/pNorm 作者源码、二进制及任何层级的源码快照不进入公开检查点。CCFA 绘图副本按 root 指定默认排除。此记录是源码范围的静态审查，不是最终 DELIVERY、全包扫描或公开上传收据；本代理未发布、运行实验、读取测量 raw/图/ZIP。

## 核验依据与边界

- 当前普通实验冻结的 27 项源码全部逐文件 SHA-256 匹配 `provenance/source_snapshots/formal_ordinary_v12_002/receipt.json`，共 118719 字节；该 receipt SHA-256 为 `35aff994c5d7fc355e13194c7d5f9cb6ea9e1a7e281a76d33bb9144e648ec074`。这证明受核源码与冻结版本相同，不替代许可判断。
- 实际阅读了 `THIRD_PARTY_NOTICES.md`、作者获取元数据、原许可文本、适配器/构建下载入口及绘图副本来源。许可判断以原文本为准。没有扫描结果目录或归档成员，也没有对最终公开候选逐文件作内容排除审计。
- root 确认发布目标仓库已有 MIT，原创源码沿用该仓库根许可；不在本地研究目录另立整体许可证判断，也不把 MIT 自动扩展到上游材料。公开 commit 应实际保留目标仓库原 LICENSE。
- 初次写文档因文件系统 ENOSPC 在 shell 创建临时文件时失败，未执行核验程序/写文件；root 释放自己的重复缓存后，才完成上述只读核验和本文件写入。未删除他人文件。

## 原创源码与入口

| 范围 | 紧凑检查点处理 | 说明 |
|---|---|---|
| `zrhfd/` 原创 Python/C++/Julia 适配代码 | 可发布源码 | 包括图/CSR 存储、扩散、sweep、mincut、certificate、pipeline、prepared workspace、hypergraph 及 baseline adapters；第三方库通过安装/下载调用。`mincut128.cpp` 是项目构建源，不需要附编译产物。 |
| `zrhfd/baselines/hfd.py`、`pnorm.py`、`native_driver.jl` 等薄适配器 | 可发布本项目适配源码 | 调用用户单独获取的固定作者仓库；不包含 `ucHFD.jl`、`pNormDiffusion.jl` 等作者实现。适配器可公开不意味着作者目录可公开。 |
| `zrhfd/baselines/acl.py`、`tlhfd*.py`、`hfd_cd.py` | 可发布，保留来源与身份说明 | ACL paper port、TL* 独立 Algorithm-1 port、同目标坐标求解控制不能冒称原作者执行代码或新数学定理。LocalGraphClustering 来源信息和许可记录保留。 |
| `experiments/` 原创 worker/schedule、数据生成、分析、诊断、存储/恢复控制、重现入口 | 可选择发布源码及必要小配置 | 冻结 measurement 与后续工程/分析版本保持现有 pins；不为发布改变 source/config。不能把目录中的上游绘图副本或 M0 附件兼容实现一概标为全部原创。 |
| `tests/` 本项目验证代码 | 可发布源码 | 附件原内容、作者仓库文件、嵌套环境/快照不因位于测试目录而获得再发布许可。 |
| `REPRODUCE.sh`、`experiments/reproduction/`、`experiments/build.py` | 可发布本项目代码、lock 和小来源 receipt | 提供固定提交/版本下载、本地构建与 fresh 输出入口。公开源码不声称全部 M0–M6 已重新执行。 |
| `external/acquire_sources.py`、`external/acquire_julia.py`、`experiments/data_generation/provision_lfr.py` | 可发布这些本项目脚本 | 与脚本下载/复制出的第三方目录和 runtime 分开选择。`acquire_sources.py` 的旧首次 clone 是 HEAD 获取再记录 commit，独立使用不能等同于 pinned fresh 重现；应以已锁定的重现 driver/lock 为规范入口。 |
| `experiments/plot_helpers/ccfa_plot_recipes.py` | 默认不上传 | 实际是 CCFA MIT 副本。若选中的公开 plot 入口需要 import，必须同时保留原 MIT、署名、commit 和副本 SHA，不能改标原创。 |
| `experiments/m0_reference/core.py` 及旧附件来源 | 不作无条件原创放行 | 该 shim 明确由给定附件 kernels 重构且旧原 core 缺失；紧凑检查点默认不携带附件原件或其来源未闭合的副本。M0 历史精确重现缺口继续明示。 |

受核 source27 的具体范围为：`zrhfd/` 下 `__init__.py`、`certificate.py`、`diffusion.py`、`experimental_cut_workspace.py`、`graph.py`、`mincut.py`、`mincut128.cpp`、`pipeline.py`、`sweep.py`；`zrhfd/baselines/` 下 `__init__.py`、`_common.py`、`_execution.py`、`_native.py`、`acl.py`、`hfd.py`、`hfd_cd.py`、`leiden.py`、`native_driver.jl`、`pnorm.py`、`tlhfd.py`、`tlhfd_numba.py`；`experiments/` 下 `ablations.py`、`catalog.py`、`common.py`、`protocol_v12.yaml`、`schedule.py`、`worker.py`。source27 以外的原创辅助代码不冒称属于该 27 项 measurement freeze。

## 上游目录与许可

| 实际目录/材料 | 固定来源 | 已见许可与公开处理 |
|---|---|---|
| `external/hfd/` | `s-h-yang/HFD`，`f4111f7fa2ceb44a99acdf8057a609b7322e1ebf` | 获取 receipt 的 LICENSE 列表为空，再发布权限未核实。排除原源码、binary、编译/JIT cache 和任何嵌套源码快照；保留 URL/commit/hash 下载记录。 |
| `external/pnormflowdiffusion/` | `s-h-yang/pNormFlowDiffusion`，`ba0f59e6a1863d30a6198f5ab45b8ebc880ef93d` | 同样未找到 LICENSE；处理同 HFD。实际路径不是 `external/pnorm/`。 |
| `external/generators/lfr_native/` | LFRbenchmarks，`ec9a860282d8fc9d52e9e08fea9ce93ddeb473af` | 原 MIT；若选择源码必须携原 copyright/许可及 generator pin。紧凑检查点可仅留固定下载/编译入口及图生成/输入哈希；默认不携旧原生 binary。 |
| `external/localgraphclustering/` | `a6325350997932d548a876deb259c2387fc2c809` | 原 MIT，Copyright 2020 Fountoulakis/Liu/Gleich/Mahoney。默认留获取/归因记录；若携上游源码保留其完整许可/署名。 |
| `external/leidenalg/` | `d7cbb3ee6f29d1214b96c0f4dd120c609c6cca65`，package 0.12.0 | 仓库许可为 GNU GPL v3。默认不 vendor 源码/binary；依赖安装及许可独立保留，不改写为项目 MIT。 |
| `external/runtime/`、Julia depot/发行包、Combinatorics | Julia 1.10.10，Combinatorics 1.0.2 | Julia MIT 加 bundled library 各自条款；Combinatorics MIT。紧凑公开包排除环境、runtime、depot、下载 tar 与 cache，保留官方 URL/checksum/version receipts。 |
| CCFA 绘图副本/skill 来源 | commit `5969e6b20a3bbcef9118fa00796d1417d48fcbf3` | MIT 原文位于 `provenance/skills/CCFA-Skills_LICENSE`；副本 SHA `242d49c21cd31a6cdcad17e45a322d0cb30e3b57620259c193ef28993100ff66`，来源 `provenance/plot-helper.json`。按 root 本次默认排除副本。 |
| Supervisor-Skills 来源 | commit `207bc6f7a1aa107e544099c2c7cc86816fba9628` | CC BY-NC-SA 4.0；与项目 MIT 分开，不默认上传 skill 原内容。保留来源/pin 和原许可记录，不作全仓 MIT 归属。 |
| `external/papers/` 论文 PDF/抽取文本 | 固定 primary-paper URL/version/hash | 本次不上传论文及其内容副本；只保留来源元数据。 |
| Benson/Trivago 官方原 archives、给定 `inputs/` 附件 | 各下载/附件 receipt | 公开可获取不等于当前记录授予数据/附件再发布权。本次不因本地使用而默认发布这些原第三方材料。 |

已见许可原文件 SHA：LFR MIT `a8b6e154af89470602cf49961ae333036085778cf75ce331ea1abe0d9e46826c`；LocalGraphClustering MIT `cbf58f48f45f9fb166989a8f89f90eee5dfc27cfa826142c7fbb764dbaa8e5aa`；leidenalg GPL `589ed823e9a84c56feb95ac58e7cf384626b9cbf4fda2a907bc36e103de1bad2`；CCFA MIT `1ac138d752fc345d61c5790df57caed3487e4d66d59879d6bd60272765d087d2`；Supervisor CC BY-NC-SA `b35c958b79726c115cf817635abcbc2aa1121cae5e9a1c22819f7c44f58fcaf0`。

## 本次不上传的历史与材料

紧凑检查点不自动包含完整历史 `results/` raw/checkpoints/ZIP、旧 DELIVERY/研究归档、fresh 环境与下载/runtime、全部来源快照和大型 CSR 规模输入。root 可选择本轮原始 covers、summary 投影、本项目生成图/真值、来源和输入 hashes；本记录没有核其实际候选 bytes 或替这些数据作许可放行。尤其作者原代码可能处于 `provenance/source_snapshots/`、fresh payload 或历史归档的深层路径：路径改名不会改变排除要求。第三方 binary 同样不放行。

发布说明应明确实际保留和未上传的范围，继续保留历史缺件、失败/timeout、部分阶段未完成及 fresh 只完成安装/8 toy/分版本控制器恢复的边界。不能将本轮公开检查点称为完整历史精确重放、全部 fresh 科学重跑或最终 DELIVERY。最终候选排除、目标根 MIT 确认与 GitHub 上传 receipt 由 root 完成；本代理没有执行上传。
