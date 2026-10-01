# ZR-HFD v1.2 可执行实验协议

本协议落实用户冻结规格，不改变其定义、命题或关卡。主配置在 `experiments/protocol_v12.yaml`；任何后续工程修复须保存原测量、源码快照和原因。既有M0/M2结果属于开发复现，test 36图尚未评价方法质量。

## 输入与选择

新test是原生无权无向LFR，n∈{1000,10000}，目标实测vol-weighted真值conductance为0.1至0.6，每档3图，共36图、432个预先固定单种子查询。所有图首个生成attempt即达到预先±0.025容差，最大偏差0.001756。`-k=20`是生成参数，实际均度并非恰好20；逐图值保存在输入统计。dev为附件四图、24个新SBM及同批12SBM参考图；被引用但缺失的12个NetworkX图保持MISSING，不用别的输入冒充。catalog和逐查询清单的SHA固定在协议和数据审计中。

主算法只接graph、seed、冻结配置。真标签仅进入输出评价、预先抽取查询和明确标注的oracle体积参考。R-supp与R-cap(1/2)使用四张附件图48个查询和24张新SBM的288个查询作配对dev比较，按用户规则仅当差值bootstrap 95%区间下界>0才改变主区域，记录变更；该选择不得读取test结果。其余主语义保持冻结。

## 基线与资源

HFD运行作者Julia源码p=2、σ=1e-4、50轮。p-norm运行作者p=4、50pass上限、ε=1e-3、cm_tol=1e-2。HFD-CD是同二次目标的高精度工程求解器加conductance sweep控制，和作者HFD独立列示。TL*是Algorithm1的直接端口，采用经weighted逐步核对的Numba等价实现（Numba编译/缓存和更新计算都包含于wrapper完整时间；该端口尚无独立JIT/kernel字段）；原文未给实验实际step size，显式使用constant η=0.25，zero start、best-dual返回、γ=1、1000轮，完整unit fractions[.01,.02,.03,.05]。这个step是工程输入，不称论文默认。单独保留theory schedule的smoke结果。ACL采用lazy push，α∈{.01,.05,.15}，精度尺度ρ=1/m；Leiden采用原生modularity、resolution1、seed73、迭代至无改善，取含seed的块。

无体积局部基线使用与主算法相同的起点3d_s、倍增和M/2上限，跑完整网格，以输出conductance选配置；不在结果出现后加主方法独有的提前停机到基线上。oracle组只接真实vol(C)标量，质量3vol(C)，ACL使用ρ=1/vol(C)，独立标注。所有方法同图同seed；作者原生tie处理保留，主方法不拆tie；TL*/ACL含seed筛选明确记录。每项任务CPU1线程、串行、墙钟上限600s、内存上限12GB；超过预算记TIMEOUT及partial cover，不能用截断耗时当完成耗时。默认不重跑算法失败；环境／实现修复可有一次明确另存的重跑。

同时报告wrapper完整时间、作者kernel时间及启动／转换时间。Julia进程开销和Python/C++差异不得归因于数学方法。主方法触及体积按冻结的支撑并集∪区域；边界读取、稠密分配和原作者全图扫描另列。开发工程可与独立核验并行，但不能作为正式速度结论；正式测量会标记录并发任务状况。

## 实验与统计

主表记录冻结M4全部指标；bootstrap固定seed20261005、10000次，先重采样graph再重采样其queries，保留方法间配对，分别输出均值与中位数区间。按每个查询真实φ(C)分组；G-E2严格用实测φ的≤.5及≥.4条件，不用native μ代替。超时、ERROR及partial不混进完成质量表，同时给全计划任务数、有效配对数和完成率。

十八项消融在每张可用dev图的既定清单前两个查询上运行，原始main/cap配对另外覆盖全部dev查询。固定网格对应旧质量猜测50至6400乘3且受M/2预算；多起点为S0、单点和seeded hull-best，以精确Z选结果；这都是另名变体，不替换主方法。TL*扩散变体在同质量、同σ的固定f网格里用Z-sweep选择，明确与主二次最优求解误差比较。test仅在算法与协议冻结后作最终评价，使用后不调参。

真值诊断在输出完成后进行，包括C⊆R、ρhat、区域外体积、m_c的相对1e-4容差二分和单步间隙余量。诊断时间单列，算法看不到标签或m_c；不把诊断成本算作在线检索。不能覆盖真值的H1与区域内恢复失败H2分别列出。每条测量保留source/config/input哈希、实际命令、cover、diffusion/MM/certificate轨迹、错误与内存，summary可由原JSON重建。

## 已发生的停止与协议风险

G-E0在冻结通用域为FAIL；T-b小超边等价、未限定凹性的G凸性和V(c)空支撑已写精确反例，不自行修订。继续ordinary graph与unit all-or-nothing子域。G-E1也已实测FAIL：R-supp虽0/12并入K30，但两条查询F1下降超过.01；保留失败，不把“不并入”当完整验收。M3–M6仍执行，未知项目写NOT RUN。真实Trivago使用Benson修正后的官方合法超边文件；旧HFD仓库最后token重复错误保留为来源审计。

## M6冻结时间与斜率协议

9张规模图、108个既定单种子query，按catalog逐图/逐query串行。fresh子进程先在无真标签toy readonly int32/int64/float64 CSR上预热相同Numba签名，编译/缓存与backend初始化单列；正式CSR加载/校验单列。热method wall包括扩散、sweep、MM、区域证书和输出stats/components；总query成本另列imports、warmup、input加载、hash和offline评价。600秒/12GB覆盖全部子进程，超时不是完成耗时。

斜率主分析为每图query热时间中位数的log时间对log n回归，按独立graph bootstrap；同时给query层面及控制log真值volume的敏感性分析。完成率、超时和ERROR按n列明，不能只在完成子集中宣称全任务次线性。G-E3需要触及体积/输出volume中位数≤20且时间斜率<1；置信区间与实际只有每档3个图的限制同时列明。CSR总数组大小/真值社区大小例外保留，不将mmap加载时间当算法成本。

## 实现版本与汇总防护

在首次test质量计算前，采用容量逐字节等价的prepared-region cut工作区作为ordinary正式工程实现002：仅缓存静态拓扑与外部边界，不改变目标、质量序列、排序、停止或接受规则。小oracle26项及真实query的270次cut完整轨迹验收通过；新ordinary首12配置输出/评价与旧版一致。每个原始记录的source/protocol SHA和job关联唯一对应实现manifest；新M6还直接记录implementation_version及request版本。汇总前独立检查source、query、配置和manifest一致性。

旧ordinary001、旧M6及所有中断/失败保留为前一工程版本，不与新版本成本合并；新版本对全部既定查询重新执行，不只运行慢例或失败。只有完成指定预算的结果进入完成表；有时间截断或中断的cover、checkpoint另列，不当收敛或完整certificate。缓存的输入数组/区域只读使用，图不会在任务中改动。
