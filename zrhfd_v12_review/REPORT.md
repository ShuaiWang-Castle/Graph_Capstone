# ZR-HFD v1.2 执行报告

当前状态：**ACTIVE**。目标是完成M0–M6，或按冻结停止条件保留书面结论与证据。冻结定义在 `provenance/goal-objective.md`，原附件按哈希留在 `inputs/`。

当前主实验进度（2026-10-01T16:50:32.176593+00:00）：ordinary002 dev4032、test5184、dev消融1008项全部完成，共10224项。dev与test逐cover／来源审计PASS，消融独立配对审计PASS。**ZR-HFD开发集平均F1=.983286，但独立test平均F1=.684915，低于原生HFD的.898986；G-E2为FAIL。** 主方法总体中位数1掩盖困难图的失败尾部，不能声称稳定质量改善或同质量加速。原owned父调度器仍在ordinary分析屏障HELD，当前无消融测量子进程；dev336详细诊断控制器已exit0、结果尚待独立审核。test432详细机制诊断因G-E2 FAIL明确NOT RUN。M5官方真实超图主面板尚未运行。恢复控制v003已PASS，完整fresh科学cohort尚未重跑；早期进度段落只作历史证据。

给Claude／GPT的最新独立审核请求在 `GPT_PRO_ANALYSIS_PROMPT_ZH.md`，已纳入完整test负面结果与dev消融；特别区分泛化失败、基准过拟合推测和不同图分布的混杂。用户已明确授权本轮GitHub审核快照更新，冻结主方法和test调参禁令不变。

按照冻结§2.1，普通图目标 `Z=1−normalized modularity` 是已有目标。本文检验给定pipeline的恢复质量、成本、区域证书与失败机制；缓存拓扑、整数容量工程和存储编码按工程实现报告。理论陈述由理论方负责，数值核验仅覆盖明确列出的有限实例。

## 里程碑与关卡

| 项目 | 当前状态 | 已有证据／尚缺工作 |
|---|---|---|
| M0 | NOT RUN（部分已完成） | 同rng59的12SBM参考新运行与两份附件旧JSON全部字段一致；远处团重建的24条F1/Z等7字段与旧记录精确一致，低编号2/12、高编号0/12。原core、s12原查询及12张NetworkX输入缺失，不能升级为原逐查询完全复现。 |
| M1 | FAIL（适用域；核验已完成） | 冻结通用域的精确反例保留；独立有限核验和普通图工程核心穷举交叉验证完成，未影响子域PASS。不是证明。 |
| M2 | FAIL | 144条任务，134完成、10条budgetM扩散截断；主设置全部完成。远处团四组均0/12并入，但R-supp两例F1下降超过.01，G-E1失败。 |
| M3 | NOT RUN（缺失历史cohort；现有数据／基线已完成） | 36校准LFR test/24SBM dev、720预定查询与源/输入哈希固定；作者HFD/p-norm、ACL、TL*、Leiden真实smoke及现有dev／test完整面板完成。原12张NetworkX输入在已接收与已检索材料中未找到，缺失范围不称完成。 |
| M4 | FAIL（G-E2；主实验与消融执行完成） | dev4032／test5184／消融1008全部完成并独立审计；主表与质量—成本图已产出。dev区域672配对保持R-supp；dev336详细诊断已返回、尚待独审，test432详细诊断依冻结规则NOT RUN；旧001的96项保留，不混合成本。 |
| M5 | NOT RUN（核心与输入准备完成，部分域硬停） | 单位全有或全无的精确cut/MM小规模核验完成，官方contact327/Trivago1000查询已冻结；一般分割T-b等价／凸性范围仍硬停。 |
| M6 | PASS（执行与负面报告完成） | 全108项已终止：99完成、8超时、1数值求解错误；完整原始审计及独立固定9个q00审核通过，4张图／12输出可读。数值故障同输入原代码重现并定位。G-E3局部性FAIL；runtime次线性仍未建立。旧实现13完成、1排程中断保留。 |
| G-E0 | FAIL | 当前冻结的一般超图命题已出现违例；仅暂停受影响部分，普通图和其他独立检查继续。 |
| G-E1 | FAIL | low/high×supp/cap均0/12并入；supp两例下降超过.01，最大下降.537179；cap无下降，但整体关卡仍FAIL。 |
| G-E2 | FAIL | 完整432个查询三元组通过独审；φ≤.5的324查询，ZR／Leiden中位F1均1，margin PASS；.4≤φ≤.5的68查询，ZR=.950820、HFD=.985507，+0.10增益FAIL。 |
| G-E3 | FAIL（局部性条件） | 独立精确比值核验：108项已有58项触及/输出volume>20，超过半数，9个未知值不能使整体中位数≤20。runtime次线性仍未建立；原自动摘要与completed-only斜率保留。 |
| G-E4 | NOT RUN | 真实超图对照尚未运行。 |

## 已观察到的数值现象

三元超边 θ=1、w=[0,1/2,1/2,0]、M=3、v=1，冻结期望定义给出G=2/3，而冻结小边等价给出1/3。详细最小实例及影响范围见 `THEORY_REQUESTS.md`。尚未修改任何定义或以变体替换主方法。

单独的普通图P1–P8、非空V、FP/MM-exact等检查在已运行有限实例中未见违例，不能据此称证明或使整体G-E0转PASS。原始范围与分母见 `results/m1_independent/exact_claim_checks.json`。

## 决策记录

- 本项目使用独立目录和Python3.12虚拟环境；已有研究、原测量与打开的LaTeX稿件不参与这次实现。
- 主实验设置CPU 1线程、串行测量；并行源码阅读和工程核验耗时不会充当最终性能表。
- 保留用户冻结算法；参考脚本的并列值拆分、seed-first遗漏和浮点min-cut规则作为差异记录，不能覆盖规格。
- M1采用精确Fraction与高精度KKT核验；近似扩散的误差仅作为遥测，不据此制造反例或放宽命题。
- 出现T-b反例后，先记录并停受影响子域，继续普通图工作；不因单个反例删去M0–M6的原始范围。
- 20m坐标更新后截断属于求解器未完成。保留v1代码快照和10条错误，增加同二次目标的稀疏active-set linear finish；不是算法改动。10条原错误全部重跑完成，9条精确恢复、same12_10仍差一个点（F1=.997996，已有TR006目标边际诊断），不将原截断耗时当完成时间。
- 区域下界原版精确hull+float64极值评估保留；后续加入80位Decimal外向舍入区间，普通图240个cut、30个hull、135个MM步等工程交叉核验再运行0违例。
- 正式无体积基线完整倍增到M/2，TL*使用完整paper f网格、ACL三档alpha；明确TL* eta=.25为工程输入，非论文实验默认。配置见 `experiments/protocol_v12.yaml`。
- Trivago使用Benson官方修正数据。旧HFD每条末节点重复一遍，官方去重与之逐行等价，但总volume726861与旧960063不同；论文mean degree约5.6与旧版一致，不能声称新输入逐值复现论文。
- dev第一次六条任务存在completion_claim元数据缩进错误；原raw保留并注明，canonical配对使用修复后的 `results/m4/dev_region_v12_002`，不覆写初始数据。
- M6阶段采用父调度器屏障：仅暂挂本项目的调度器，当前测量子进程继续按原600秒预算运行。108查询子进程全部结束后，先串行完成独立审计与绘图，再唤醒同一调度器进入M4；屏障期间不启动重复workflow。实际身份与信号记录见 `results/orchestration/m6_analysis_barrier_v001.json`。
- 在test质量尚未运行、768项详细诊断尚未执行时，发现原复现入口会无条件运行test诊断，与冻结§5的“G-E2未通过时只在dev图上诊断”不符。保留完整计划及原9项诊断源码，增加独立关卡外层：test只有同一冻结cohort的完整G-E2为PASS才运行，否则432行写NOT RUN及原因；不回填test的H1/H2机制分层。既有primary质量评价、主算法、冻结查询和预算不改。更正前辅助源码保存在 `provenance/source_snapshots/diagnostic_scope_pre_correction_v001/`。

## M4 ordinary002 开发集真实主面板

全部28图、336查询、12设置共4032项COMPLETED，0个failure文件；完成表示执行了请求预算，不表示每个fixed-iteration基线已收敛。实际10,000次graph→query bootstrap（seed20261005）与全分母表在 `results/m4/dev_main_v12_002/`。独立stdlib审计逐条从输入图与cover重算F1／precision／recall、精确割／体积／Z、phi与连通分量，核来源、CSV与均值／中位数：`reviews/m4_analysis/actual_dev_v001/receipt.json`，PASS，SHA `9a8142ffeca08caf84db0c53fbfb5196db379a73dd468c0b49570fd10b331a9a`。没有重新运行算法或独立重采样CI端点。

| 不给体积／全局对照 | 完成／计划 | F1均值 [bootstrap 95% CI] | F1中位数 | wrapper中位秒 |
|---|---:|---:|---:|---:|
| ZR-HFD | 336/336 | .983286 [.959183, .999414] | 1.000000 | .413303 |
| HFD（作者实现） | 336/336 | .855877 [.821110, .888771] | .908034 | 1.075704 |
| HFD-CD | 336/336 | .777812 [.733345, .821394] | .798496 | .073706 |
| TL* | 336/336 | .777812 [.733345, .821394] | .798496 | .366157 |
| ACL | 336/336 | .803348 [.755611, .847290] | .846561 | .031648 |
| p-norm（p=4） | 336/336 | .789163 [.747323, .830209] | .812308 | .618559 |
| Leiden（全局） | 336/336 | 1.000000 [1,1] | 1.000000 | .216535 |

五个oracle设置也各336/336完成，完整表独立保留；其F1中位数依次为HFD 1.000、HFD-CD／TL* .892857、p-norm .898881、ACL .489049。oracle值不是主方法的调参输入。没有把更低的oracle成绩删除或换成最优质量网格。

这是开发集信号，不能用它替代G-E2；独立test的G-E2实际FAIL见下一节。主方法逐查询对Leiden的F1差均值−.016714，配对bootstrap95%区间[−.040817,−.000586]，中位数差0。实测phi≈.5组24查询F1中位数.992424，但均值.819325。没有主方法singleton输出；全部失败及回归字段保留。dev详细诊断已完成并汇总，当前尚待独立结果审核，不把新的诊断view当原方法耗时。

wrapper包括相应adapter启动／转换，不含框架外Graph.load或离线评价；作者HFD另有native kernel中位.154210秒，不能把wrapper优势当算法加速。ZR-HFD的平均wrapper .528825秒，certificate cut执行与返回验证合计均值.314665秒；后者含子进程启动，不是纯kernel，各嵌套阶段时钟不相加。区域gap中位.113782，即使恢复质量很好，也不能把MM驻点写成R内全局最优。已有telemetry的描述存于 `reviews/m4_analysis/actual_summary_dev_v001/`。

质量—成本、实测phi分层与所有计划分母三张PNG已查看，无裁切；对应9个PNG／PDF／SVG及来源在 `figures/m4/dev_main_v12_002/`，实际QA见 `reviews/m4_analysis/actual_dev_v001/plot_visual_review.json`。完成此次串行离线窗口后，同一owned父调度器已从M4dev屏障RELEASED进入冻结test。M4方法／图／配置／预算不变，没有利用test结果调参。

## M4 ordinary002 独立测试与开发消融：当前完整结果

同一输入／查询，无真实体积的局部设置；Leiden为全局种子社团对照。dev28图336查询，冻结test36张新校准LFR图432查询（n1000／10000）。每个设置均全部完成。主表给平均F1和test中位F1，避免只选有利统计量。

| 方法 | dev平均F1 | test平均F1 | test中位F1 |
|---|---:|---:|---:|
| ZR-HFD | 0.983286 | 0.684915 | 1.000000 |
| HFD（作者代码） | 0.855877 | 0.898986 | 1.000000 |
| HFD-CD（高精度二次目标控制） | 0.777812 | 0.733490 | 0.890935 |
| TL*（论文Algorithm 1复现） | 0.777812 | 0.733490 | 0.890935 |
| ACL | 0.803348 | 0.731773 | 0.887245 |
| p-norm p=4 | 0.789163 | 0.770856 | 0.936699 |
| Leiden（全局） | 1.000000 | 0.947315 | 1.000000 |

ZR-HFD test平均F1的图级bootstrap95%区间为[.591644,.777533]；对Leiden的配对F1均值差−.262401，95%区间[−.339921,−.186332]。dev／test主方法均无singleton输出；这说明v1未激活就停机的症状在这些查询中未出现，不能排除其他激活后失败。

按实测真值conductance的展示分箱中心.1/.2/.3/.4/.5/.6（每箱72查询），test平均F1依次.986698/.919831/.797918/.600618/.520342/.284082。展示箱与G-E2精确筛选不同：.5箱覆盖[.45,.55)，不能把该箱全部视为φ≤.5。以上仅为primary质量分层；test详细H1／H2机制诊断不运行，不拿失败test调参。

运行成本：test ZR-HFD平均2.734442秒、中位.352864秒；作者HFD平均1.403137秒、中位1.471463秒。这是包含适配器转换／启动的算法wrapper时钟，排除外部输入加载与离线评价；HFD native kernel平均.372193秒，不与ZR wrapper混用。ZR证书cut执行／返回验证阶段平均2.123093秒、中位.213063秒，包含子进程启动，嵌套时钟不可相加。质量均值下降且平均成本上升，**尚无“同质量更快”结论**。

18个变体×56个dev查询=1008项全部完成；独立cover／来源／配对统计审计PASS。关闭MM相对主方法平均F1差−.210131，配对95%区间[−.260643,−.159465]；说明MM在这批dev上有实际贡献，不说明test改善。R-cap(.5)差−.084613[−.122757,−.049408]；扩区supp(j*+2)仅+.000446[0,.001785]，budgetM仅+.000520[−.000215,.002076]，没有充分证据通过简单加预算获得稳定大收益。该56查询消融不替代336配对的区域主规则预登记，且未作多重比较校正。

证据：`results/m4/{dev,test}_main_v12_002/quality_cost_summary.csv`；test独审`reviews/m4_analysis/actual_test_v001/receipt.json`（SHA e90eea4816d9f3d5273dfc712eb30d10f0b948e37d37ea0b00ccd9135da5690f）；关卡`actual_test_v001/G_E2_independent_recheck.json`；消融`reviews/m4_analysis/paired_ablations_v001/{receipt.json,paired_statistics.csv}`（收据SHA199473040431d8db53ddc79f4577be2b1275fd73714929d354be1f95ee738612）。dev／test质量—成本图均已生成并查看。审计PASS只说明记录与计算一致，科学改善关卡仍FAIL。

## M2 已有实际测量

| 工程设置 | 完成/计划 | exact | mean F1 | min F1 |
|---|---:|---:|---:|---:|
| same12主R-supp/P3 | 12/12 | 10 | 0.994325 | 0.933902 |
| same12 R-cap(.5)/P3 | 12/12 | 6 | 0.859878 | 0.480480 |
| same12 R-supp/P2 | 12/12 | 10 | 0.924738 | 0.098859 |
| 初版budgetM | 2/12 | 2（仅完成子集） | 1.0（仅完成子集） | 1.0（仅完成子集） |

M2两张附件μ=.5图的主方法F1中位数为0.992424/0.989130；与相同新查询的重建全图版本1.0/0.993671相比，差为−0.007576/−0.004540。这是实际matched-query比较；s12旧0.996503因原查询缺失，不能用新查询代替复现。完整JSON、输出cover、diffusion/MM/cut/hull轨迹与错误在 `results/m2/`。

独立M1报告 `reviews/m1_independent/INDEPENDENT_M1_REVIEW.md`：随机超图48高精度解，16,672含seed子集；单位Mono21次无违例，cardinal Mono21次仅观察。普通图工程核验16,742组体积/割/Z、240个精确cut、30个hull及76个不动点全部通过。首轮31个fixture拒绝与纠正原因均保留。

## 未决问题

见 `THEORY_REQUESTS.md`。完整实验与来源状态将随着实际运行更新，NOT RUN不填成PASS。

M5正式启动前的静态检查发现：作者HFD native adapter保留最终dual heights、有限50轮预算和请求但未应用的tolerance，当前未生成缩放KKT／质量守恒、seed最大和support连通的完整遥测；小图CLARABEL核验不能替代正式native轨迹的这些量。缺失遥测不写成0或PASS。先准备从保留score独立离线重算的方案，固定source与逐mass分母、单列分析成本，不修改正在测量的普通图源码或冻结主方法；并列值的任选subgradient残差不能冒称最小KKT残差。实际补足工作尚未运行，后续如资源使其无法完成将明确保留NOT RUN及原因。

## 开发集区域预登记结论

`results/m4/dev_region_v12_002`全部672任务完成，0错误。336个相同图/seed的配对中，R-cap(1/2)−R-supp平均F1差−0.0925556，按图再按query的10000次配对bootstrap 95%区间[−0.1245845,−0.0634509]，描述性中位配对差−0.0040161。冻结规则要求区间下界>0才换主区域，故保留R-supp。这里使用test查询0条。原始摘要和每条raw哈希在`results/m4/REGION_DECISION.json`。开发时与其他工程核验并行的时间不会作为正式速度结论。

## 规模输入与测量范围

全部9张规模LFR和108查询通过输入审核，catalog SHA cfc6bf3b22a9ee71880f3a3dd656d3637b3b89a9d5dad9172f5b142a93a889e5。三张百万节点图实际原生生成289.16–314.50秒，峰值3.83–4.10GB；这是生成成本，不是ZR-HFD算法成本。原生社区size输入100..200有3个实际尺寸例外（222/220/214），全部保留；108个查询的目标社区都在100..200内，没有重采样避开质量失败。只读CSR数组约245MB，mmap元数据加载约0.0038秒/63MB峰值不代表全部页已读取，方法读图成本在真实运行中测量。

## 新增工程决策

- 加入HFD-CD高精度同二次目标＋conductance完整网格控制，和作者HFD单列，检验精度差异，不能把它冒称作者复现。
- TL*普通图同Algorithm1的Numba端口已在16个weighted fixture与literal核对；不换损失或传播规则，Numba编译/缓存和kernel包含wrapper完整时间，作者Julia的native kernel单列；不声称TL*有独立编译计时。
- 核心新增可选checkpoint回调，不更改质量、排序、接受或停止规则；超时留最后扩散/region/MM状态，partial不是收敛证据。
- dev区域002的13项源文件已逐字节匹配原manifest哈希保存至`provenance/source_snapshots/dev_region_v12_002/`，原始测量不可覆写。

## 首批规模阶段profile（未完成整轮，不作斜率结论）

`lfr_scale_n10000_s202610061_q00`：算法hot38.9983秒，扩散合计.03678秒；区域2230点、vol48527、输出180点，触及/输出volume=13.6274，F1=1.0。精确hull136个顶点、267次min-cut调用，cut执行及返回校验合计12.1761秒（该旧字段不是纯native kernel），完整证书还重复准备拓扑、边界和Fraction容量。独立prepared region workspace作为同精确算法的工程原型开始，不更改目标/停止/区域；本批旧source/runtime原样保留，未来不同实现成本不得混到一个版本。首批13条已完成查询的原始cover均不是singleton；耗时短的例子应按实际输出大小、质量和激活轨迹报告，不能仅凭运行时间推断退化输出。

M6控制器因安排串行工程核验主动中断一次，记录`results/m6/engineering_interleave_001.json`；13条已完成结果保留，正在证书阶段的query标interrupted并保存partial，不把它算算法失败或完成耗时。后续相同冻结规格/配置采用精确容量等价的prepared实现另存完整108-query cohort；原实现前缀按实现版本保留，不混合时间。研究goal仍ACTIVE，不改已冻结规则或只保留快例。

补充逐cover核对：13个完成查询中8条F1=1；5条输出3–5点，F1=.0248–.0548，j_act均2、j*为2或3。快例不是singleton；此前报告的该推测措辞已更正，编辑前版本与纠正收据保留在`provenance/report_corrections/`。这些结果只说明当前前缀，不能代替全体108查询的质量／速度统计，也不能把小输出导致的快耗时当同质量加速。

## prepared工程实现版本002（test质量前冻结）

26项小规模独立oracle检查和一个真实10⁴查询均确认缓存前后的整数容量、arc顺序、cover及精确目标一致。真实查询全部270次cut、完整MM及136点hull/LB一致；工程hot38.9983→16.0925秒仅作为单例profile，不当正式速度统计、不声称新原理。缓存只准备一次区域拓扑与完整外部边界；每次unary仍使用原LCM、force、128位容量、原图返回目标核对，图和区域在缓存生命周期保持不变。

原普通001的96个结果及原M6的13完成/1中断完整保留，新的4032 dev主面板、5184 test、1008消融与M6全部108查询分别另建manifest，不将两个实现成本混入同一表。主Config、图、query、600秒/12GB预算均不变；新source27项、binary和依赖锁在`provenance/source_snapshots/formal_ordinary_v12_002/`。新ordinary首12个同输入方法均COMPLETED，cover与评价全部逐值匹配旧记录，主方法MM/hull/LB亦相同：`reviews/prepared_backend_adoption/ordinary_first12/actual_integration_checks.json`。

M5最终八方法interval整合smoke8/8、故障存储/资源fixtures6/6与35项源码锁通过；正式11480任务已冻结尚未启动。这些检查只验证接口和工程，不充当真实超图结果或论文成绩。

## 首个普通图查询的实际基线结果（描述性，非总体结论）

新正式002的首个固定dev查询来自附件 `lfr_n1000_o00_m20_s11`，seed550，真值24点、实测conductance .207161。以下均不给体积；完整12设置包括oracle参考保存在 `results/m4/first12_descriptive/quality_cost.csv`，每行指向原始cover及SHA。

| 方法 | F1 | algorithm-wrapper wall（秒） | 独立native kernel（秒） |
|---|---:|---:|---:|
| ZR-HFD | 1.000 | .6640 | 不单列 |
| HFD（作者实现） | 1.000 | 1.9081 | .08760 |
| HFD-CD（高精度控制） | 1.000 | .07391 | 不单列 |
| TL* | 1.000 | .2989 | 不单列 |
| ACL | .960 | .03007 | 不单列 |
| p-norm flow（p=4） | 1.000 | .6296 | .1819 |
| Leiden（全局） | 1.000 | .2846 | 不单列 |

wall包含相应适配器、格式转换与启动成本，但不含框架外部Graph.load及离线评价；Julia native kernel另列，不能把跨语言启动差异当成算法收益。这里只有一个query，不给bootstrap区间，也不能判定“同质量更快”。这一例的高精度HFD-CD与其他强基线已达到F1=1，后续仍按全部固定query比较，保留质量与成本失败。

## 规模首个十万节点超时与存储

`lfr_scale_n100000_s202610061_q00`在600秒上限超时，最终可用checkpoint已完成MM并进入区域下界certificate阶段，R包含73179点、当时cover287点；没有完整hull/LB，不能把600秒当完成时间或把checkpoint当收敛证书。其他同档查询已正常返回，最终分母仍是全部108，不以单例推整体。

受本机约6GB剩余空间限制，采用measurement结束后保存的无损编码：M6用APFS透明压缩保持全部原路径和bytes/SHA；M5用逐member校验的ZIP/index，可由archival.read_bytes/read_json恢复原路径字节。失败和中断一样保留。存储代码与实际命令/用时单独归档，不计入已结束的算法/parent receipt时钟，不修改图输入。标准文件内容和方法源码冻结版本保持不变；这些存储操作不作为算法性能收益。

M5正式开始前，存储外层固定为 `provenance/storage_wrapper_v004/receipt.json`，当前指针与receipt SHA在 `provenance/storage-wrapper-current.json`：≥64KB的文本成员采用ZIP-LZMA，小成员DEFLATE，已有编码文件STORE，保留逐member真实编码方式与SHA。原因是预定Trivago native输出包含172738维height及重复的全体touched节点checkpoint，本机空间有限；这是源码结构支持的容量预防，不声称实测整个M5的压缩率。四种终止状态的人工bytes恢复及旧ZIP重建index检查通过；额外8种有效terminal状态、6种未结束／未知状态与已有index状态gate验证通过，坏receipt不进入expanded cleanup。原v001/v002/v003外层源码和收据保持历史。全部35项M5测量源码、输入、配置和测量时钟仍不改。大批真实数据验证仍由正式存储smoke和后续audit完成。

外层记录的 `offline_archive_and_verification_seconds` 尚不包含index发布及最后的expanded verify/delete；它不是完整存储成本。整阶段controller时钟包含这些工作，已终止的方法receipt时钟不包含存储操作。独立v004小字节重建20项检查通过，不能替代正式八方法存储smoke或完整真实archive审计。

M6父调度器的 `controller_wall_seconds` 还会包含人为安排的阶段屏障等待；这一总调度时间不作为方法成本或跨规模斜率的输入。方法与每query监视器的已测时钟、超时判据均不受父进程暂挂影响。准备中的磁盘监视器只在剩余空间严格低于2.5GiB时，请求同一owned调度器正常中断，并先保存恢复证据；它不强杀其他进程、不自动重启，也不改变算法选择。

## 已激活但仍早停的具体失败轨迹

十万节点固定规模查询 `s202610061_q09` 在j_act=2、m=84时支撑已达3点；随后质量168/336/672的支撑增长为5/7/10点，最优Z-sweep却连续保持同一精确比值，P=3按冻结规则耗尽。j*=2令R取下一档支撑，仅5点、vol55；真值173点、vol3021，最终3点、F1=.022727。此例有激活，也执行了区域MM与完整证书；区域gap约1.11e−16不能说明恢复了真值，因为C⊄R。

另外两条已完成查询输出8与4点、F1=.072727/.021277，同属H1。三条hot约.022/.031/.018秒只是低质量快速返回，不能作为同质量加速证据。它们是明确选出的事后诊断，全部108任务仍是最终频率分母。原始记录、SHA和KKT／质量／Z轨迹在 `results/m6_analysis/preliminary_h3_examples/examples.json`；相关条件问题已写TR007。没有修改主方法耐心、区域、质量网格或预算。

## M6完整批次的实际结果

全部固定108查询已经终止，计时与原始文件均未因后续核验改变。独立审计 `results/m6_analysis/prepared_audit/receipt.json` 为PASS（SHA `c99f8e4e95c38f8e2f6465fbef77bb82ec42647da0859c03fe1c9433aa1e0bdb`）：验证全部source/config/request/terminal/result绑定，并从固定truth、cover和只读CSR独立重算99条完成质量与局部统计；不使用production评价函数或导入NumPy/算法。审计通过表示记录一致，不表示算法恢复或关卡通过。

| n | 完成／计划 | 超时 | 错误 | F1均值（完成子集） | F1中位数（完成子集） | exact | H1 | H2 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10⁴ | 36/36 | 0 | 0 | .597872 | 1.000000 | 21 | 15 | 0 |
| 10⁵ | 32/36 | 4 | 0 | .495919 | .562311 | 11 | 14 | 7 |
| 10⁶ | 31/36 | 4 | 1 | .425012 | .430440 | 6 | 13 | 12 |

失败查询没有质量填值。上表仅描述完成子集，分母与失败单列，H1/H2来自固定primary离线评价字段的独立核对，没有为失败查询启动额外真值探针。全部99条完成的触及/输出volume中位数23.789474，超过20。按9张图的完成子集hot中位数拟合，log n斜率.091299，图cluster bootstrap 2000次95%区间[−.287687,.396977]；调整真值volume后为.201437，[.038330,.439814]。这些拟合受8超时与1错误的删失影响，不能宣布完整次线性关卡通过，也不能把低质量小输出的快时间当同质量加速。

4张实际图位于 `figures/m6/prepared_v001/`，分别展示hot／触及比、质量与hot、parent删失时钟、全部完成分母；SVG/PDF/PNG共12输出已查看4个PNG，坐标与标记可读。输入/audit/summary/CSV及图来源SHA写在figure provenance；描述表 `results/m6_analysis/prepared_audit/quality_descriptive.json` 不新增统计选择或调参。

独立实际审核见 `reviews/m6_analysis/ACTUAL_M6_REVIEW.md`（SHA `42e34608ac82fa7e231469b186b2f5dc9c5e7007e8287c25c652720c5d9676ec`）：核对全部99条完成质量统计、9图中位数、6个OLS point estimate，并按预先固定的每图q00读取实际cover/truth重算，8条吻合、1条timeout保留原位。精确Fraction触及比确认58个已观察值>20，占全部108项超过半数；即使9未知值都低于20，也无法使108项中位数≤20。故G-E3局部性条件FAIL，不填补9项未知值；runtime次线性仍未建立。原自动摘要的 `NOT_ESTABLISHED_INCOMPLETE_COHORT` 不改写，completed-only斜率不升级为完整规模结论。

数值错误发生于 `lfr_scale_n1000000_s202610063_q10`：active-set linear finish未满足degree-scaled stationarity阈值，29.626秒后报错，没有最终cover/证书。诊断探针在原16项源码、原configuration和图SHA下重现相同异常，原记录未覆写：`reviews/solver_failure_probe/run_v001/`。m=10,616,832，active289,765点，CG info=0；重算relative RHS L2 residual为8.5995×10⁻¹⁴，但max degree-scaled residual为2.1313×10⁻⁸，超过1×10⁻⁸验收阈值。所有解值为正，没有负值clip影响；第一个扩张步新增1点，第二步无新增点却未通过驻点残差验收。CG成功与外层驻点验收使用不同残差尺度，不能由CG info=0推出外层验收通过；此记录不识别唯一数值根因，也不是已证命题的反例。探针28.895秒只作诊断耗时，不作为主cohort retry或完成性能；NPZ保存active节点及clip前后值，源码／数组SHA和完整命令、资源、错误trace均保留。不放宽原阈值、不替换原失败。实际源码／记录复核23项通过，见 `reviews/solver_failure_probe/independent_actual_review.md`（SHA c5620567f444f818e0c417da080ee1ace7f342aa4d623248b34c9f8ee4d4e1b4），限于metadata与源码、未独立重算大数组。原与探针trace都指向pipeline.py:77，故障是j*+1的R-supp支撑补算，m=10616832超过主schedule M/2=9517383；规格允许这一补算，不将其误记为主质量网格超预算。

## 汇总与复现的证据边界

M6主表、删失说明、图和实际独审已完成；M4 dev／test完整主表、bootstrap、绘图及消融独审已完成，M5官方完整面板仍NOT RUN。图表只使用完整预算并带有效completion claim的质量，计划分母包括未运行、超时和失败；oracle体积参考单列。768个主方法查询的详细诊断计划保留全部行；其中test432条须通过G-E2执行关卡，未通过则不运行或生成test机制分层，primary质量评价仍保留。dev诊断的H2目标偏好依据精确 `Z(out)−Z(truth)`，不把带penalty的间隙余量误当目标差。

一键复现将重新生成输入与manifest，并用显式reference binding核验相同冻结图字节、查询、配置与任务，不把新生成的created/runtime元数据伪装成旧测量。dev binding没有G-E2资格；只有完整冻结test的432个有效查询三元组可以判定G-E2。上述接口的人工schema检查属于工程验证；真实空目录安装及八方法smoke已经执行，恢复环节失败，尚不能宣称完整端到端复现通过。


## 实际全新目录安装与恢复失败

`../zrhfd-fresh-smoke-v001` 从不存在的目录开始，独立安装35项固定Python依赖、获取4个固定author commits与原论文、安装task-local Julia/Combinatorics，并编译LFR和min-cut。21项安装命令全部成功；8项非正式toy方法全部COMPLETED，读取并核验每个存储archive member的SHA通过。记录在 `reviews/reproduction/fresh_setup_smoke_v001/summary.json`；原项目与fresh源锁同为ced744428a47567023901422a70af954e05c0160dd0618c288134453948fd486。fresh LFR binary与原binary不同而source commit相同，build identity明确记录，未伪称字节相同。

随后真实controller中断恢复测试报 `PermissionError(1, 'Operation not permitted')`，外层exit1；本次观测wall95.9105秒、峰值采样RSS909,180,928 bytes、最低采样剩余空间1,930,743,808 bytes。这是复现控制器的工程失败，不是算法质量失败。原异常只保存repr，尚不足定位具体调用行，不能先猜原因或写恢复PASS；完整失败attempt/log、21项成功安装receipt及8toy原始结果全部保留。三个测试后代均确认退出，未执行成功恢复attempt001。当前对受影响helper进行最小兼容修复与完整trace留痕，另绑定版本后仅重测恢复部分；主方法／测量source pins和参数不变。真实fresh full M0–M6科学重跑尚未执行。成功与失败的实际证据已复制入项目交付树 `reviews/reproduction/fresh_setup_smoke_v001/payload/`：200个文件、879421 bytes，逐文件复制SHA核对，snapshot SHA为c9cea08b4eaf506d65472a5dcbc0044e7c8a8b9726498198178d51c12eaa4e4a；包含8方法原始archive/index、toy图、命令receipts与恢复失败记录，不只是外部路径。

实际fresh独立审核的64项小型metadata／源码检查一致，见 `reviews/reproduction/independent_actual_fresh_v001.md`。仅用于留完整trace的recovery-only准备通过有边界的审查；源／锁／marker显式迁移在 `reviews/reproduction/control_version_migration_v002/`，科学测量源码与协议不变，原ced整轮不改记PASS。

带完整trace的实际v002仍失败（exit1，terminal wall1.202628秒），见 `reviews/reproduction/actual_recovery_only_v002/`。两组正PGID 70961／70962的SIGTERM都返回成功；0.5秒后，driver.py:445向旧PGID 70961发送SIGKILL时报PermissionError。未执行第二组KILL或后续wait。测试后的三个具体owned身份均已不存在。现在能定位失败操作，但记录不足以断言操作系统拒绝的唯一原因；不会吞掉权限错误或把这次失败记为恢复成功。原v001不覆盖。兼容修复仅针对控制器：持有PID及创建时间，在升级信号前重新核验存活身份，跳过已退出或zombie；真正仍活的权限错误继续保留并失败。

在实际安装／八方法结果及独立审查完成后，回收本次自建fresh Julia runtime、depot和下载tar，保留2131项文件／链接／SHA清单、17份许可证、原始结果和完整安装命令，见 `reviews/reproduction/fresh_runtime_cleanup_v001/`。剩余空间由1,899,421,696增至2,561,433,600 bytes。原项目的Julia及全部科学数据／结果不变；fresh Python环境暂留给受影响恢复检查。这是容量维护，不是算法加速。

最小held-PID修复的实际v003检查随后通过，outer wall1.268681秒、内部fixture1.157077秒，见 `reviews/reproduction/actual_recovery_only_v003/summary.json`（SHA067ee9654140984889f04c25aec1d42f9f2167cf783c4ff46a2ec2e6f79172b0）。同key的attempt000保留中断终止，attempt001成功返回；四个owned身份已退出。root在实际fresh解释器下只读核验全部28项proof哈希与终止身份通过；最初使用原项目解释器因argv身份不符被正确拒绝，未重跑fixture。41个文件／382195 bytes的实际proof已复制入交付树。新版本控制器恢复PASS不覆盖v001/v002 FAIL，不宣称整套fresh科学cohort已重跑。

随后仅移除本次fresh `.venv`，保留12241项文件／链接／SHA及219份installed metadata／许可证，见 `reviews/reproduction/fresh_runtime_cleanup_v002/`；剩余空间增至3,041,460,224 bytes。原科学调度器3597已经从屏障RELEASED，继续M4 dev，实际owned磁盘guard开始监视。11:06 UTC文件清单为240个dev原始结果、0个failure文件；这是在运行的文件库存，不是240项质量验收或总体改善结论。dev／test／消融与后续M5计划、预算及全部方法源码不变。

## 本次GitHub审核快照与dev诊断

用户于本轮明确授权更新GitHub。公开目录zrhfd_v12_review是中期checkpoint，项目仍ACTIVE；不自动授权未来发布。全部10224个普通图最终cover已在独立标准库projection replay中核验：F1/P/R/size/cut/volume/精确Z/phi/seed-membership与冻结任务/输入身份0差异；实际收据reviews/publication/actual_cover_replay_v002.json。该重放不是原生算法复跑或全solver witness审计。紧凑ZIP25,266,123bytes，SHA48c6ab44aa20b6bcd4de6cd08a1ea88fee3856793ab3f6f95c9c2f428060b83e；24份首查询完整原raw sample另保留，其他10224条为明确缩减的派生projection。

dev详细诊断336/336 COMPLETED，summary及primary join已实际执行；独立诊断数值结果复核尚未完成。295精确恢复、15 H1、26 H2；H2中5例output具有更低Z、21例区域内可行truth具有更低Z。只报告已有dev诊断，不由test选择规则；test432条详细诊断为NOT_RUN_G_E2_NOT_PASS。汇总见results/diagnostics/m4_main_v12_001/analysis/quality_failure_crosslist_summary.json。

存储曾拒绝small writes及summary输出，失败日志保留，未当算法失败；仅清理本任务自建fresh副本中可重新获取的Git对象/未测量上游notebooks，完整文件SHA留存。原实验输入、源码和全部测量未删除。主workflow仍HELD，M5官方0/11480；完整最终DELIVERY与最终独审未完成。
