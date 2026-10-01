# M6 独立离线核验入口

当前状态：**代码与小型 stdlib fixture PASS，真实完整 cohort audit NOT RUN。** 不调用冻结方法、生产 Graph/evaluate、NumPy 或绘图库，不在测量子进程内部运行。主入口是 `experiments/m6_analysis/audit.py`，默认输出为 `results/m6_analysis/prepared_audit/receipt.json`。

入口核全部 108 个固定查询、9 个图与三个 scale 的 36-query 分母。它校验16个冻结来源、当前配置、实际依赖 distribution fingerprint、catalog、CSR/truth/query 字节；对所有 attempt 保留 request、controller、terminal、checkpoint、result/error、stdout/stderr 与完整文件清单的 SHA。未完成、timeout、memory、error、interrupted 和旧 attempt 都保留，不能把存在 method_result 当作正式完成。

已完成 outcome 独立使用只读 `.npy` mmap 与整数 CSR 局部访问，重新计算 truth/output 的 volume、cut、Z、F1、hull-F1、完整社区 cover、C⊆R、rho、outside volume、H1/H2 和 touched ratio。它逐字段核 raw offline 评价，并把当前 CSV 的每一个单元格与独立 raw 投影比较。未完成行没有 F1/cover 等完成评价。统计回归和 bootstrap 不由这个入口重新拟合；完整性能关卡仍由 root 依据未删失 cohort 评估。

auditor 自身源码在开始核验时固定，并加入结束时的统一字节复核；长时间离线读取期间若来源改动会拒绝发出 PASS 凭证。

供 root 在串行 CPU 空档执行的命令如下，本次尚未执行：

```sh
.venv/bin/python experiments/m6_analysis/audit.py
.venv/bin/python experiments/plot_m6.py --audit-receipt results/m6_analysis/prepared_audit/receipt.json
```

`verify_audit_receipt(receipt_path, run_path=None, verify_files=False)` 默认只读取当前 manifest/config/source、summary/CSV、auditor 及小型 receipt metadata；它返回 `status=PASS`、cohort origin、implementation、manifest/summary/query CSV SHA、108 denominator、completed count、status counts、实际 receipt SHA 和 files-reverified 标志。它交叉核完整 query identity、全部 attempt census、完成质量记录的 query/attempt/F1/coverage/H1H2、未完成质量 mask 与每个 CSV 字段。`verify_files=True` 才重核完整输入/原始文件清单。

默认 canonical receipt 是可更新的派生证据：若已有效则重核；若同一 cohort 继续测量导致旧 receipt stale，先按旧字节 SHA 保存到同目录 `history/`，完整重核成功后才原子更新 canonical receipt。输入、原 raw、冻结 source 和任何 algorithm timer 都不改。不可读或尚在变化的文件拒绝通过，需在 quiescent 时重新 summary→audit→plot。轻量 plot 验证不宣称再次完整读 raw。

小型人工图/metadata 证据：`STDLIB_TINY_v004.json` 有43项 PASS，包括独立4点环精确体积/Z、F1/覆盖/H1/H2、NPY只读访问、失败质量 mask、CSV漂移拒绝、完整108人工身份 control、空/改动 receipt、错误 quality query/attempt/F1 和缺失 attempt 拒绝。人工 metadata 验证仅测试 schema 关联，不是一次真实方法测量。v001–v003 历史证据及各自 source SHA 保留，d891 前版源与其43项 receipt 已按字节保存在 `source_snapshots/`，独立 review 另记录其受检版本。
