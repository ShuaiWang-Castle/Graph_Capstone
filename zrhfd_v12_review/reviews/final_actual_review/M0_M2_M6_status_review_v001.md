# M0–M2／M6 状态与最终判定口径独审

**ACCEPT_CURRENT_STATUS_PRESENTATION_WITH_OPEN_COMPLETION_PREREQUISITES。没有发现需新停止普通图测量的状态误报或主定义替换；科学最终 PASS 不予授予。** 本次只核对现有小摘要、协议、源码与已完成独审，不运行数值测试、Graph／NumPy、bootstrap、ZIP或大 raw 审计。

| 项目 | 准确状态 | 证据与边界 |
|---|---|---|
| M0 | NOT RUN，部分重建复现 PASS | results/m0_reference/summary.json：两份 same12 新 JSON 与旧值／SHA一致，24条远处团的7字段一致。旧 core、s12查询／逐查询结果、12张旧 NetworkX 输入缺失，REVIEW.md明确未完成原逐查询完全复现。新查询不能代替旧查询。 |
| M1／G-E0 | FAIL | reviews/m1_independent/status.json把证据复核 PASS 与 literal gate FAIL 分开。普通图／unit有限检查无违例不构成证明，也不解除泛范围反例。 |
| M2／G-E1 | FAIL | summary_v12_001.json：144项中134完成、10个原budgetM截断；主项12/12。四组0/12并入K30，但R-supp两例下降 .537179／.169811，在两种编号下都违反≤.01。cap子组PASS不使整体PASS。 |
| M3 | NOT RUN，数据／smoke部分PASS | 冻结数据、接口和真实基线smoke是准备证据，完整主对照尚待M4。 |
| M4／G-E2 | NOT RUN，正式测量进行中 | REPORT.md:15,147及冻结§5:166,171。dev区域区间下界非正，保留R-supp；已有前缀／运行库存不代替完整432 test判定。test详细机制诊断只有完整同cohort G-E2 PASS才允许。 |
| M5／G-E4 | NOT RUN | unit核心与toy成功不是真实超图关卡。泛cardinality停止域仍保留；须至少一个完整预定真实面板，比较no-volume HFD并报告oracle差距。 |
| M6 | 执行／负面报告PASS | audit为PASS但all_queries_completed=false：108均终止、99完成、8超时、1错误。审计完整性不等于求解收敛、恢复或关卡成功。 |
| G-E3 | 局部性FAIL；runtime NOT ESTABLISHED | 固定分母108中已观察58项比值>20，超过半数，九项未知无法使整体中位数≤20。原automatic NOT_ESTABLISHED_INCOMPLETE_COHORT和completed-only斜率均保留，不补值、不宣称次线性恢复。 |

T-b小边等价反例是对称凹分割：n=2的G=3/4而v²/M=1/2，n=3为2/3与1/3，因此TR001不能缩成非凹问题。TR002停止未定义一般分割凸性及依赖MM/LB；unit与明确凹子域可继续，不能清除泛范围关卡。TR003的空支撑m=d_s恒等式失效与主路径m0=3d_s分开；literal V仍FAIL。TR005的M′例子不满足P8分离，保持域歧义，不报成分离域内反例。TR004/TR006/TR007分别是全图M扰动、有限样本目标失配和已激活后平台早停的经验诊断，不冒充§2命题反例或新理论。

主源码与协议未见悄悄换成变体：普通图默认3d_s、P=3、R-supp、S-first／seed-first diffusion排序、Fraction精确cut／严格Z下降接受，输出MM而非hull-best。j*+1补算可超过M/2，冻结规格本就允许。active-set finish仍同二次目标；prepared cache有精确容量／arc／cover／MM／hull matched证据，按新版本单列成本。超图主期望G与ZH-prov分开；作者有限迭代扩散和原numeric LB的精度限制显式记录，区间包络也不解除T-b。

M2原10个截断被保留；后续同目标solver修复10项完成，其中9项精确恢复、1项F1=.997996。不能把原截断时间算完成成本，也不会改变G-E1失败。M6的八个600秒超时和一个求解错误不进入完成质量／时间拟合；H1/H2只针对已有完成primary离线结果。区域MM驻点、小gap和区域LB不是全局 seeded Z 最优或真值恢复保证；support-union触及体积也不代表全部CSR读取／全图转换。

最终科学验收仍被已知未闭项阻断：M4完整dev/test/消融及固定G-E2，M5完整真实G-E4面板／统计／审计，缺失原材料的M0范围结论，完整fresh科学复现或显式停止结论，以及root交付closure和实际全member包审计。FAIL可以如实交付；不能把M6报告完成、fresh安装／toy／新v003控制器恢复PASS升级为科学全项目PASS。v001/v002控制器失败仍保留。

一个非阻断编辑差异：所读REPORT.md:160的v002 wall写1.203356秒，而canonical terminal／diagnosis均为1.202627541963011秒。建议最终refresh引用terminal；只影响控制器工程时钟小数，不改变任何方法或关卡。

所读文件的实际SHA、逐项状态／停止域与剩余条件保存在同名JSON。本审阅不改根报告、冻结协议／源码／锁，也不是最终完整科学验收。若后续根报告已修正上述小数，以本JSON绑定的版本为本次检查对象。
