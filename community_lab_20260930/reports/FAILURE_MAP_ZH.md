# 失败与开销诊断：初始全网格及实际profile

初始216任务全部终态：204完成、12超时。以下病因有源码或实际阶段证据；没有把安装故障、代理loss或未知质量当算法失败。

## BigCLAM 原生估K：时间先花在CV

n1000的12项全部完成，外层pipeline中位15.1774秒；n5000的12项全部在300秒预算内CV阶段超时，无合法cover/checkpoint，质量未知。最后观测K160或253，24–27个CV MLE完成。原生grid实际11点×3CV；n1000共有396次CV MLE，均到10000次vertex更新。源码early-stop要求iter>10000，而此处CV上限10n恰是10000，因此该上限内不可能由这一条件提前停止。最终MLE为39000–89000次更新，不能据此证明收敛。

完成子集CV的舍入CPU占原生总CPU中位94.51%；这不是外层精确wall分摊。K选择stdout/TAB/argmax12/12一致，无打印舍入造成选错的证据。源与逐项原生日志在 `work/setup/native/baseline_log_analysis/` 和 `cv_selection_audit/`。禁止用已知K免费输出替代native-K主面板，内部随机种子固定10也不伪装独立seed重复。本轮未改K选择机制。

## Ego：先丢重叠容量，已有过滤控制又改变碎片惩罚

`analysis/traces/ego_selfloop_stage_trace.json` 在n1000/o40/m50/s12记录：Karate Club通用walk检查插入1000内部自环，每点只生成一个persona；400真实重叠点、预测重叠0。最早容量损失在邻域分量前，早于全局分区。源与trace支持实现缺陷，不证明所有Ego方法有此缺陷。

去内部自环的已知修复在看开发质量前登记，但原min0版本产生许多小群，macro F1中位仅约.008–.011。5个共同案例中loopless Karate Club和修复sknetwork逐点persona数量相等，只支持中间拓扑契约，不保证全局Louvain等价。强控制保留上游现成配置：CC/Louvain/min5的n1000/n5000 macro中位.6569/.5706；真正上游默认PC/Leiden/min5为.7372/.7658。48项全部完成。不能把由现成过滤和现成聚类配置带来的改变量包装成新机制；旧min0负面全部保留。全空图upstream persona为空导致错误、混合孤立点成功的functional错误trace另存 `work/ego_controls_smoke_v1` 和 `work/ego_controls_isolate_v1`，不是LFR任务安装失败。

## NOCD：完整训练成本与数值计算候选

全部24项的阶段/外层pipeline比值中位：n1000 forward/loss/backward55.84%、sample10.86%、setup24.84%；n5000对应83.15%、3.69%、5.19%。各项比值独立取中位，不能求和当完整分摊。来源 `analysis/full_baseline_stage_summary.json`，固定501最大更新和作者bad-checks>10规则不改。

独立5步PyTorch profiler：n5000/o40/m50/s11总225.308ms；index self32.758ms、mul30.310ms、index_put self23.361ms，批BerPo loss inclusive49.373ms；n1000/o40/m50/s12总47.440ms，batch loss inclusive11.817ms。这些包含关系不能相加成可消除成本，更不能推成完整pipeline加速。coalesce只占大例约2.3%，不作为候选依据。

实际候选C1只替换批内ordered pair-dot primitive，已有CSR sampled_addmm与现成bmm直接比较。GCN、sampling、full-loss选点、epochs/patience、正则、Adam、K、threshold均原样；所有unique/CSR/inverse构建计费。计算是已知双线性恒等式，非新原理；数值顺序变化可造成质量漂移。小图准备和框架开销可能导致净负收益。候选开发288项现已全部评分，冻结gate先于首个候选质量；实际失败层和开销见下方。

## NOCD：训练目标与归属目标有差距，不能用标签回选

24完成任务全部500个实际saved cover离线评分无错误，最终cover都等于最早最低full-training-loss保存点。9/24项的事后最高macro saved point高出返回点至少.03；全部24项差值的中位为.01307；这只是诊断，不是可返回方法。例如n5000/o40/m50/s11训练loss选epoch400 macro.2179，事后epoch100 macro.2780。不能据真标签改checkpoint或训练停止，也不能由单例宣布普遍病因。

这些保存点的时钟从adapter入口起，observation/snapshot计时早于文件写盘，未测外层bootstrap偏移，因此只是离散诊断，不是完整pipeline精确time-to-quality；没有插值、没有超时冒充到达。`analysis/nocd_checkpoint_diagnosis/`保留全部曲线/JSON/hashes。独立模型artifact审计不代表收敛或归属质量。

## Highway：原生与wrapper及Python版本分开

24项完整原生结果中，C++打印TOTAL/外层pipeline比值中位n1000为5.89%、n5000为19.59%；build/TOTAL为37.32%/41.26%。低成本方法中Python启动/载入/转换占比显著，native内部时间不是完整headlining时间，省wrapper开销也不是新图算法原理。

独立Python大例profile共1.931秒：backbone.858335秒、propagation.693182秒、refine.121813秒；97592次jaccard，排序交集self.507/cum.725秒。小例.397秒：backbone.17039、propagation.14902、refine.02565。深拷贝和cProfile的诊断耗时不覆盖原基线headline。详尽阶段数组留在 `work/diagnostic_v2/`。

## 证据边界

六项独立profile的输出cover全部与原初轮对应baseline一致；两项NOCD initial/best embedding也byte相同，见 `work/setup/infrastructure_audit/diagnostic_orchestration_audit/`。阶段profile定位机制，不证明新算法胜利。本轮不继续旧项目禁用路线；不制造原理、不把已发表成绩当复现、未使用独立确认图调参。候选及三seed复核已经完成；由于冻结准入失败，独立确认未生成/运行，完整原因在候选决定和最终报告记录。


## 已知K面板中的同图强基线边界

`analysis/baseline73_v2/paired/bigclam_vs_nocd_size_diagnosis.json` 逐图核对：n5000的12/12共同完成case上，原生C++ BigCLAM/oracle-K都严格更快，并且matched macro与micro F1都高于原始PyTorch NOCD；n1000仅2/12满足这三个条件。两个方法都只拿同一K标量、不拿成员列表。该事实来自本轮同图测量，属于不同实现栈的实用成本对照，不能据此隔离推断算法复杂度；内部BigCLAM seed10与NOCD请求seed73不是相同随机轨迹。

因此C1即使通过相对原NOCD的工程加速门槛，也不能直接声称改善整个方法集合的实用质量—成本前沿。必须保留这些强基线、具体图与信息面板边界。


## 成本与资源字段的实际含义

`pipeline_seconds` 从 runner 完成输入/source hash核验后、打开日志和创建适配器进程前计时，至适配器进程退出的专用wait线程记录止；包括进程导入、训练、等待原生子程序、模型选择、checkpoint/cover写入和退出。它不含runner启动前的输入/source哈希核验、退出后的cover合法性/hash与result保存，也不含离线标签评价；适配器内部的源码/binary核验属于child pipeline计费；整轮deadline仍按真实墙钟连续计。

`peak_tree_rss_bytes` 是约0.2秒间隔采样的进程树RSS最大观察值；1500MiB是采样守卫阈值，非OS硬内存限制，瞬间峰值可能漏测。24项初轮Highway C++中19项小于0.2秒，15项仅记录245760B，不能据此宣称真实峰值或内存优胜。原数值保留，不补造高峰。CPU 1线程是环境变量和实际实现设置；没有OS线程/亲和性遥测，不声称OS证实始终只有一个线程。完整源码审计见 `work/setup/measurement_semantics_audit/`。


## C1：大图确有训练阶段收益，小图准备成本与质量漂移阻止准入

四arm、24图、算法73/74/75共288项全部完成；无候选新增失败。72个case/seed的四arm initial embedding全部字节一致。CSR66对、BMM65对更新数相同；其余都在小图。即使更新数相同，数值轨迹也可能不同；不能把“数学等价”当作输出精确相同或所有退化的因果证明。

大图36对CSR与elementwise更新数都相同，forward/loss/backward每更新成本中位降低21.6936%、20.4745%、20.7453%，完整pipeline节时18.4766%、17.1480%、17.4531%。这支持实际训练计算收益，不能只用停止更早解释。小图相同更新数子集11/9/10对的该阶段反而慢9.3650%、9.6805%、12.1302%；该子集是探索诊断，不能换掉全12对层分母。

独立profile选择同两个原先profile图，分别运行elementwise/BMM/CSR，6/6完成且cover、initial/best embedding、检查epoch与full-loss数值均与对应原C1任务一致；elapsed/阶段计时和完整JSON分别保留。五个早期CPU训练窗口：

| n | elementwise窗口总ms | BMM窗口总ms | CSR窗口总ms | CSR pair准备10次inclusive ms | elementwise gather/scatter self ms | CSR gather/scatter self ms |
|---|---:|---:|---:|---:|---|---|
| 1000 | 46.313 | 45.229 | 46.018 | 9.745 | 6.978 / 4.633 | 0.127 / 0.137 |
| 5000 | 230.604 | 252.754 | 203.760 | 10.709 | 34.629 / 21.557 | 0.176 / 0.159 |

CSR实际sampled pair-dot 10次inclusive小/大图1.748/5.679ms；已有BMM仍有大图gather/scatter约35.669/22.986ms及bmm self48.825ms。全训练CSR准备wrapper中位小/大图约0.966/1.023ms，含instrumentation；正pair unique/batch中位.6231/.9044，负pair .98985/.9996。准备成本近似不随这两个n等比例增长，而endpoint张量处理在大图更贵；这些trace支持具体开销解释，不证明所有图的普遍尺度规律。嵌套时钟不可求和，五步早期窗口不能代替全训练或完整pipeline。

CSR小图三seed都慢，且seed75 macro平均差−0.0108144000793低于冻结−0.01；边界接近也不改标准。BMM三seed、两种n全部慢。CSR相对elementwise有5项macro或micro材料退化，示例：

| case/算法seed | macro差 | micro差 | 至少两正确归属召回差 | 更新数关系 |
|---|---:|---:|---:|---|
| n1000/o00/m50/s11 / 74 | −0.069967 | −0.051388 | NA（无真实重叠） | 同数 |
| n1000/o20/m50/s11 / 75 | −0.066839 | −0.060191 | −0.1250 | 不同数 |
| n1000/o20/m20/s12 / 73 | −0.052852 | −0.024347 | −0.0500 | 同数 |
| n1000/o40/m20/s11 / 74 | −0.048474 | −0.025872 | −0.0425 | 同数 |
| n1000/o40/m50/s12 / 75 | −0.039388 | −0.029644 | −0.0625 | 同数 |

n5000对elementwise仍有两归属召回下降8/3/4项；对BMM在seed74另有一项macro下降−0.036739。主53条与补全87条退化索引均保留，见候选报告路径。完整负面和局部加速可以同时成立；不声称逐案支配、严格同质量或显著非劣效。

cap1000控制64/72对确实多更新，8对patience使更新数不增加。大图全部多算，时间变为原来的约1.80–1.89倍，平均macro仅−0.003090/+0.003085/+0.000315，micro +0.006078/+0.007118/+0.005580。它没有把NOCD大图归属恢复提高到本轮强实现水平，也不是固定墙钟比较。完整停止理由、inclusive cap更新数和轨迹见 `analysis/nocd_pairdot_gate_v1/update_counts.csv`、`cap1000.csv`、`diagnosis_supplement.json`。

## 哪些故障仍不能归成算法失败

下载/依赖/API兼容、原生构建与评价修复均有实际错误日志和补丁；正式比较以各冻结源码版本为准，不是强对手的质量败绩。稀疏ONMI评价修复在基线冻结后透明实施，只影响离线评价计算，不计作算法收益。全空图Ego functional错误另存，不删，也不混入有效LFR正式分母。正式剩余未完成仅12项BigCLAM auto-K超时，没有合法输出，不估算其质量、完成时间或收敛。

新增312项终态产物独立审计：19,875 PASS、312 UNKNOWN、0 FAIL，7,379个已保存评估cover一致。UNKNOWN均为未从模型状态重新计算embedding/full loss的范围限制；不是312项失败、收敛证明或可精确恢复RNG训练的证明。原作者三方24图身份审计另通过。源码/配置/命令/质量/状态核对与诊断足以支持本轮范围内的负面决定，不能支持未运行确认图、其他生成器、真实图或其他硬件的结论。
