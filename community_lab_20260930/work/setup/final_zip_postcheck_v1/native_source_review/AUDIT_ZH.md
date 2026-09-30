# 实际 ZIP 源码、许可证与原生 binary 独立审计

结论：PASS。只读实际 DELIVERY.zip，不依据现存 source tree 推断。

开始：2026-09-30T10:20:19.452405+00:00；结束：2026-09-30T10:20:20.105708+00:00；墙钟：0.6533052502200007秒。

工具 SHA-256：`e8d41a93a5c67c9bfa37061dee0d132303037d56912ea2bf5cb9e90d6da2e218`。

实际命令：`/Users/shuaiwang/Desktop/Xiaobai/community_goalmode/COMMUNITY_GOALMODE_LAB_20260930/.venv/bin/python work/setup/final_zip_postcheck_v1/native_source_review/audit_native_source_from_zip.py --archive DELIVERY.zip --output-dir work/setup/final_zip_postcheck_v1/native_source_review`。

检查数：`{"PASS": 1918}`；源码 tar 实读成员：1853。

- 核对 source tar 整体哈希、逐成员哈希/大小、精确成员集合及不含 PDF/环境/git/build objects。
- 核对全部8项上游许可证在真实 tar 和独立 license 副本中匹配 SOURCE_LOCK。
- 核对 LFR/SNAP/Highway 实际 Mach-O ARM64 executable 字节、native/index 锁及归档执行权限。
- LFR binary 在 tar 中；SNAP 在 tar 和 ZIP 中；Highway 的 build 目录不在 tar，实测 binary 在 ZIP 的 canonical path 与 provenance copy 中。
- 未重算整个 ZIP 哈希、未执行 binary、未测量或重评分；其余任务/模型/四报告/closeout由父审计负责。

失败检查：

无。
