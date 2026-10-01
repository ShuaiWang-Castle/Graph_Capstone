# 基线原始来源核查

当前依据：`provenance/baselines/acquisition.json` 的论文 SHA-256、下载时间和源码提交；全文位于 `external/papers/`。这里只记录已查原文和作者源码支持的工程事实，实验结果由主报告记录。

## HFD

- 论文：Fountoulakis, Li, Yang，*Local Hyper-Flow Diffusion*，arXiv:2102.07945v4；作者仓库 `s-h-yang/HFD`，提交 `f4111f7fa2ceb44a99acdf8057a609b7322e1ebf`。
- 原文 Eq. (2) 的负对偶目标为 `0.5 sum_e theta_e f_e(x)^2 + 0.5 sigma sum_v d_v x_v^2 - (Delta-d)^T x`，`x>=0`。无权二元超边、unit cut、p=2 时与冻结普通图二次目标一致。没有发现目标差异。
- 求解器不同：作者 `ucHFD.jl` 使用原问题 alternating minimization 和 unit-cut exact projection；冻结核心可采用其他经核验求解器。因此应区分“同目标”与“同数值算法/迭代预算”。
- `ucHFD` 默认 `max_iters=50, sigma=.01, p=2, bs_tol=1e-6`，固定迭代，无 KKT 提前停止。真实数据实验脚本把 `sigma` 改为 `1e-4`；Trivago/高中 unit HFD 均为 50 轮。
- 作者 `ex=max(Delta-netflow-degree,0)`，对 `ex/degree` 做 conductance sweep；在最优点该向量是 `sigma*x`，比例不影响排序。每轮更新输出，`cond<=best_cond` 时保留新集合。
- 原生 sweep 逐节点加入并列项，不强制整个 tie block；主规格的 Z-sweep 既改变评价准则，也改变 tie 处理。原生基线保留作者逻辑；如统一 tie 则另标变体。
- 源码 `update_ex!` 每轮扫描全部顶点，sweep 也调用全向量 `findall`；局部支撑不能当成实际处理顶点数。应同时报告全局分配/扫描成本。
- 源码未发现 LICENSE，GitHub API 也无已识别 license。保留来源，不据此推断可重新发布作者代码。

原始链接：[论文](https://arxiv.org/abs/2102.07945v4)、[作者代码](https://github.com/s-h-yang/HFD)。

## TL-HFD / TL*

- 名称和作者已核对：*Thresholded Local Hyper-Flow Diffusion*，Meher Chaitanya、Sebastian Dalleiger、Luana Ruiz，arXiv:2606.09340v1，2026-06-08。未检得作者执行代码；按 Algorithm 1 实现时标为 TL*。
- Eq. (1) 与 HFD p=2 对偶目标相同。Algorithm 1 每轮用旧向量计算 `A=supp(x) union seeds` 及一跳边界；先计算局部 subgradient；对 active 做 degree-preconditioned projected update；边界 push 为 `kappa=max(0,-g/d)`，按 `kappa*(d_in/d)^gamma` 取 top-k，再设置 `x_new=eta*kappa`，未选边界维持零。Top-k 的并列可任意处理，工程实现应固定节点 ID 规则。
- Unit cut 的 `d_in` 是与 active 相交的 incident edge 权重和。cardinality/submodular 的 `d_in` 额外乘以 `w_e(A intersect e)`。这两种定义不能混用。
- 原文理论给出 `eta_(t+1)=1/(sigma*(t+1))`，Theorem 3 采用 `x(0)=0`，理论返回 best-dual iterate。实验附录没有披露实际 step-size 数值/调度和 clustering 返回迭代选择；不能编写“论文实验默认”。Algorithm 1 把 step size 当外部输入，TL* 的实际选择必须显式记录。
- 真实数据 `sigma=1e-4`；Trivago `gamma=1, T_unit=500,T_card=1000`；高中 `gamma=1,T=1000`。Trivago unit fractions `{.01,.02,.03,.05}`，card `{.01,.02,.03,.05,.07,.10}`；高中两种均 `{.01,.05,.1,.2,.5}`。
- Auto-k：unit 用 `max(1,round(f*vol_est))`；card 用 `max(1,round(f*vol_est/mean_degree))`。`vol_est=max(Delta)/delta_exp`，原实验单种子 `Delta[s]=delta_exp*vol(truth)`，所以估计值实际等于真体积；不属于无体积方法。
- Trivago/high-school 的 `delta_exp=3`。Trivago 每个目标簇 100 个均匀单种子查询；高中每个班全部学生逐个作种子。每簇选最低 output conductance 的 f，平局选更小 f；不能按 F1 选配置。
- Trivago 原文 Table 5 的十簇为 KOR、ISL、PRI、CRM、VNM、HKG、MLT、GTM、UKR、EST。v1 PDF（下载全文行2397）及 v1 HTML Table 2 均报 n=172738,m=233202，与 Benson 现行 ZIP 一致。2026-10-01 更正：本文件此前写为171495/220758，是本次来源报告转录错误；没有 primary 来源支持，也没有发现 PDF/HTML 或版本差异。
- 论文 cardinality splitting 是 `min(j,|e|-j)/floor(|e|/2)`，属于归一化凹 cardinality profile；它不等于任意满足上界的 cardinality 函数。关于用户冻结 T-b 的适用性由理论方裁决，本核查不修改定义。
- 仍有实际数据统计差异：官方修正 Trivago 总体积726861，均度约4.2079；HFD旧错误 raw 总incidence960063，均度约5.558。TL 正文和 Table 2 报均度约5.6，与旧重复token版本的统计数值吻合，但原文没有 data hash，不能据此确认实验用的是哪一版。使用现行合法官方数据时应报告这个 volume/degree 差异，而不误报 n/m 差异。

原始链接：[论文与 Algorithm 1](https://arxiv.org/html/2606.09340v1)。

## p-norm、ACL、Leiden、CFSP

- p-norm 正确作者代码是 `s-h-yang/pNormFlowDiffusion`，不是 LocalGraphClustering 主分支。原文 ICML 2020，Fountoulakis、Wang、Yang，arXiv:2005.09810v3；源码用 randomized coordinate minimization，`p>=2, mu=0,max_iters=50,epsilon=1e-3,cm_tol=1e-2`，按最大 excess 或 pass 数停止，再做 conductance sweep。`p=4` 是论文实际基线；单种子质量通常为目标体积三倍，主设置应另用不读 truth 的质量网格。
- ACL 原算法为 lazy-walk local push；输出按 `p/degree` sweep。LGC `acl_list.py` 实际执行 `p[u]+=alpha*r[u]`、保留 `(1-alpha)r[u]/2`、向邻居按权重分发另一半；默认 alpha=.15。用于核对 wrapper，不将别的 flow 算法冒充 p-norm。
- Leiden 使用原生 `leidenalg` 和 igraph，modularity 对照为 resolution=1 的 RBConfiguration 或 Modularity partition，取包含 query seed 的簇。random seed、迭代数和 package version 均须记录；全局方法 touched vertices 为全部图。
- CFSP：Bühler、Rangapuram、Setzer、Hein，ICML 2013，arXiv:1306.3409v1。它提供带硬 seed/volume constraints 的 fractional-set-program tight relaxation，再用 RatioDCA；通常无全局最优保证。若实施，按照目标给实际上下体积约束并标 oracle，不能作无体积公平主基线。

原始链接：[p-norm 论文](https://proceedings.mlr.press/v119/fountoulakis20a.html)、[p-norm 作者代码](https://github.com/s-h-yang/pNormFlowDiffusion)、[LGC](https://github.com/kfoynt/LocalGraphClustering)、[Leiden](https://github.com/vtraag/leidenalg)、[CFSP](https://arxiv.org/abs/1306.3409v1)。

## 数据取得与协议边界

实际已获取 HFD 仓库自带的完整静态带标签 contact-high-school 和 Trivago 文件，并获取 Benson 官方 Trivago ZIP；raw 文件完整保留。`data/external/trivago-clicks` 仍指向作者旧 raw，不能作为合法集合超边输入；`data/external/trivago-clicks-official` 指向官方修正 raw。逐文件 hashes、有效性与统计见 `hypergraph-data.json`。

Benson 的 [static labeled high-school](https://www.cs.cornell.edu/~arb/data/contact-high-school-labeled/) 为327/7818；不可拿 [temporal high-school](https://www.cs.cornell.edu/~arb/data/contact-high-school/) 的时间戳 simplex 文件直接替代。两个官方 ZIP 均已实际获取并记录 download receipt。其 [Trivago 页面](https://www.cs.cornell.edu/~arb/data/trivago-clicks/) 为172738/233202。官方 ZIP 的 README 明确记载 2021-11-21 修正了旧数据每条超边末顶点重复的问题。HFD 保留的233202行每行恰好有一个末token重复；官方233202行均为顶点集合。逐行比较：对 HFD 旧 raw 保序去重后与现行官方超边完全一致，节点标签和标签名称文件字节相同。此处不改旧 raw，不把它误当现行官方输入。

作者 `cardHFD2.jl` 的 odd-rank projection 存在未核验实现疑点：`update_subgrad!` 使用 `r_1[ind+1]=0` 而非排列后中间坐标 `r_1[sorted[ind+1]]=0`，且没有先清空 `r_1`。这不影响 unit-HFD adapter；本次 native hypergraph adapter 仅接 θ=1、w=[0,1,...,1,0] 的集合超边，其他 family 明确拒绝，不修改原作者源码。

可执行设置区分：no-volume 主面板只接 seed/graph、固定的质量/精度网格及固定停止预算；oracle 面板单独接 `oracle_volume` 数值。可下载的真实数据版本完整保留。十簇/100次查询应在运行结果前由主协议固定种子序列；所有方法复用相同 queries。

## 已交付的执行与核查路径

普通图 `zrhfd/baselines/` 提供真实 CPU 作者 HFD/p-norm、ACL lazy-push、原生 Leiden 和 TL* Algorithm1；接口均为 `run(graph,seed,config,oracle_volume=None)`，不接真标签。HFD/p-norm 原源码文件 hash 在调用前核对，作者文件未修改。Julia1.10.10 官方 aarch64 tarball、Combinatorics1.0.2 的版本/许可保存在本项目 `external/runtime/`，archive/package receipts 在同 provenance 目录，没有全局安装。

TL* 普通图配置可显式 `backend='numba'`；默认 literal 保留。CPU 编译实现禁用 fastmath 和并行，使用相同旧向量局部梯度、同时更新、top-k ID tie 和 best-dual 返回。16个人工随机加权图的一步与1000步末向量误差为0；best-dual向量差最多约1.01e-10，其中一个近收敛 best-iteration 选择受 objective 累加舍入顺序影响。`same12_00` seed18 拓扑-only 同28配置/28000步，输出集合、touched、全部conductance和配置相同，objective最大abs差约4.95e-10。工程耗时 literal13.886s、Numba约.213s，不当作正式速度结论。原始 checks/profile 追加记录在 `reviews/baselines/`，人工 smoke 与真实方法质量证据分开。

成功和超时 native 调用均在指定 `artifact_directory` 独立UUID目录实时保存实际命令、environment overrides、inputCSV/driver hashes及stdout/stderr。内部超时解析已完整完成的JSON并标PARTIAL_TIMEOUT，不能声称完整mass grid。真实 subprocess timeout 人工 fixture 核对已完成：超时前打印的一条JSON和stderr均保留；外部 scheduler 硬kill时 live files亦不依赖 handler 收尾。

M5 独立接口在 `zrhfd/baselines/hypergraph.py`：`run_hfd/run_tlhfd/run_acl(h,seed,config,oracle_volume=None)`。unit-HFD 调用原作者超图 solver；TL* 用真实 supplied Lovasz primitive；只有声明为 ACL 的方法用 incidence-degree-preserving clique expansion（pair权重θ/(rank−1)），其全局转换成本包含在outer runtime。新连接路径在一个小人工超图上核对，unit与weighted normalized-cardinality的Algorithm1一步与独立全局梯度相同；这些不是M5质量结果。

官方数据查询清单为 `data/external/m5_queries.json`：327个school成员各一次、Table5十个Trivago簇每簇100个不同均匀成员，具体NumPy rng20261004序列为明确工程输入；原文没有披露实际随机seed序列。原文参数、完整f grids、500/1000轮和所有 unknown/deviations 集中在 `m5_source_protocol.json`。cardinality top-k必须显式 `activation_scale='vertex_count'`，unit为`'volume'`。未执行真实M5质量比较或读取结果进行调参。
