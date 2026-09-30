# 已完成 NOCD artifacts 完整性审计

审计UTC：2026-09-30T05:46:44.536845+00:00。只读取 baseline73_v2 已终态 COMPLETED 的 NOCD 任务；没有执行算法、读取真标签/evaluation_only 或质量分数。

本次快照审计 6 项，通过 6 项，失败 0 项；跳过 0 项。逐文件 SHA-256、实际shape、checkpoint epoch、所有检查在 nocd_completed_audit.json。

检查涵盖 initial/best embedding 有限、形状/K一致、best embedding >.5 解码与最终cover逐组一致、best_model.pt weights_only加载与有限state、saved epoch/loss对应trace首次最低full训练loss，以及文件读取期间未变和prediction hash与runner记录一致。

这仅证明该快照内推断artifacts的一致性；不证明收敛、恢复质量、全部基线任务完成。未终态/尚未出现的任务需要后续重跑审计。

可重跑：`OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/python analysis/artifact_audit/audit_completed_nocd.py`。
