# M6 offline audit 独立准备审核

结论：**ACCEPT_PREPARATION_WITH_LIMITATIONS**。受检最终 `experiments/m6_analysis/audit.py` SHA-256 为 `e0ad27382c12ae2493491b717c618e23381832e43e9a465eca4f8fe6da45a461`。本轮只读源码与既有小 fixture 收据，另用 stdlib 运行人工 metadata 收据 fixture，**5/5 PASS**。真实108-query audit、真实 CSR/raw/derived 哈希与 quality 重算仍 **NOT_RUN**；准备接受不代表 G-E3 或数据完整性已实际通过。

主路径确认：

- `audit.py:240–313` 核 config/source16/依赖身份、完整108、3档各36、9图各12、固定catalog/CSR/truth/query SHA与schedule identity。读取 truth 和 CSR 仅用于离线检验，没有调用生产 Graph、扩散、cut、NumPy或统计 helper。
- `314–385` 枚举全部 query 的全部连续 attempt，核 request完整字段、实际命令/cwd/预算/version、terminal/request/result/logs/hash 与 final checkpoint。completed 要求 returncode=0及完整formal raw上下文；未完成不重算质量。旧attempt、partial/progress等原logical file均进入逐文件SHA inventory。
- `140–174,348–372` 独立整数 CSR/Fraction stats与完整 truth质量/coverage/rho/H1H2核对原raw，含 output/hull/seed/region/touched集合关系；不把区域gap当真值恢复。
- `177–219,386–410` 对原raw→CSV每个cell逐项核对；108行包括NOT_RUN/timeout/未终止，不补完成质量。summary分母、by-n、完整性与raw一致；当前输入和derived bytes在audit末尾重核。统计fit不在此处重新拟合。

初读发现 `verify_audit_receipt` 只核 completed quality 记录数量，未核身份与字段，且 receipt rows 没有与 current CSV逐cell比较。该非冻结 helper 缺口已由owner修复；受检最终 `417–522` 现在核 current CSV、非completed质量字段拒绝、completed质量唯一query集合及attempt/F1/hull-F1/coverage/H1H2、allattempt计数/path/status及fileinventory绑定。独立人工fixture确认合法108元数据接受，以下四类拒绝：quality绑定timeout query、timeout夹F1、receipt F1不等bound CSV、independent quality不等completed row。见 `independent_receipt_fixture.py` 与 `independent_receipt_fixture_results.json`。首次人工control只构造一个case，被新增scale census拒绝；随后修正为9×12/3×36后才计5项结果，没有把fixture构造错误计作validator PASS。

长offline运行的自身源码绑定也已补齐：`audit.py:237–239` 固定实际执行文件的canonical路径并把起始SHA加入inventory，`:398–399` 末尾重核，返回缓存的起始SHA，避免运行中编辑导致receipt标为未执行的新bytes。d891版本源码与43项收据由owner保留，本审查旧版记录另在 `independent_previous_d891/` 保留。

owner的 `STDLIB_TINY_v004.json` 43项收据SHA与受检源码一致，v001/v002保留历史。这些小检查不是实际108 audit。

限制：默认 `verify_audit_receipt(...,verify_files=False)` 重新核manifest/config/source16/summary/CSV/auditor及metadata语义，不重新读取全部graph/raw；只有True才重核既有full file inventory。PASS表示审计所见快照完整一致，不证明一般理论、方法收敛、uncensored全cohort性能或统计估计。必须在实际离线、文件静止时运行完整audit；后续恢复或新增attempt/重写summary后旧receipt可能过期，应重新派生并按工具规则保留旧receipt history。本轮没有真实signal、算法、Graph/NumPy、大raw遍历、PDF/ZIP操作，也没有改冻结16项测量源码或owner helper。
