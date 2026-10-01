围绕新方案推进：# GOAL（Codex goal mode）：ZR-HFD——区域内 Lovász 比值精化的局部社团检索（冻结规格 v1.2）
目标一句话：在不知道目标社团体积的前提下，实现并充分检验 ZR-HFD（HFD 扩散 → Z-sweep → 区域内 Lovász 比值 MM 精化 → 区域下界证书），在普通图与超图上与 HFD / TL-HFD / ACL / Leiden 做同输入、同协议的比较，产出可一键复现的代码、原始结果、关卡状态和报告。
完成标准（Definition of Done）：M0–M6 全部完成或在停止条件处有书面结论；REPORT.md 中每个关卡有明确的 PASS / FAIL / NOT RUN 及证据；所有失败结果保留；THEORY_REQUESTS.md 列出需要理论方裁决的问题。
本文件取代 v1 与 v1.1。 v1 保留在同目录 CODEX_GOAL_PROMPT.md 仅供对照。
v1.2 相对 v1 的改动（先读）
1. 停止规则缺陷修复（最高优先级）。 普通图上，支撑在 m ≤ m_act = d_s + (1+σ)·d_s·min_{v∼s} d_v/w_sv 时恒为 {s}（§2.3 命题 A）。v1 从 m_0 = 3·d_s 起"连续两次不改进即停"，在 m = 12·d_s 停机；只要种子所有邻居的度都不小于约 11，就在任何激活之前停下并输出 {s}。12 个 SBM 实例上 v1 全部输出 {s}（m_act/d_s 为 20–56）。v1.2：耐心只从第一个 |supp(x_j)| ≥ 2 的 j 开始计数，耐心 P = 3。超图上全有或全无超边（|e| ≥ 3）不会被种子单独拉动其中一个点，激活按集合发生，所以用"激活后计数"而不是 m_0 = m_act。
2. 区域主规则改为 R-supp（即 v1 的 R = supp(x_{j*+1})），R-cap 降为变体。依据：同一批 12 个 SBM 实例上，R-supp 精确恢复 10/12，R-cap（θ = 1/2）6/12，R-cap 的 6 个失败全部是真值社团不在区域内。v1.1 曾把 R-cap 定为主规则，现撤回；预登记的比较规则方向随之反转（§5）。
3. 超图主目标改为期望割零模型 Z_H（理论已证）；v1 的暂定版保留为变体 ZH-prov。
4. 证书：加入区域下界 LB_R、间隙 gap = Z(S_final) − LB_R、hull-best 变体，以及间隙界的遥测量。
5. 断言与遥测：种子取最大值、支撑连通且含种子、vol(supp) ≤ m 与精确质量守恒残差、质量单调（普通图与全有或全无超图）；cardinality-based 超图的单调性只记录不断言。
6. 命题清单更新（§2.3）：加入 V、Mono、A、Leak、T-c′、FP、MM-exact；P6 换成一般形式；P7 的体积界在超图上也已证。
7. 带真值的诊断（只用于分析）：覆盖、ρ̂、区域外点体积、首次覆盖质量、单步间隙余量、失败归因。
8. 新增消融：耐心 2 与 3；网格比 2 与 √2；起始质量取 m_act 的变体 ZR-mact。
0. 分工与权限
- 你（Codex）负责全部工程：实现、数据获取与生成、基线、实验、性能优化、复现、报告。工程决策由你自主决定，包括语言与库、max-flow 算法、数值容差、并行、缓存、代码结构、实验调度、何时放弃一条不划算的工程路线。每个重要决策在 REPORT.md 的"决策记录"中写一行理由即可，不需要请示。
- 理论由 Claude 负责：第 2 节"冻结规格 v1.2"中的定义、算法语义和命题陈述不得修改。你可以提出替代方案，但只能作为另起名字的变体实现和报告，不能替换主方法。
- 发现与第 2 节矛盾的数值现象（反例、违例、无法满足的断言）：立即停止受影响的里程碑，把最小可复现例子写进 THEORY_REQUESTS.md，然后继续做不受影响的部分。不要绕过，不要打补丁让测试通过。
- 只用 CPU；不做 GPU。
1. 背景与输入
- 问题：给定图和单个种子 s，不给目标社团体积，找回 s 所在的社团。
- 靶子论文：
  - HFD：Fountoulakis, Li, Yang, NeurIPS 2021，https://arxiv.org/abs/2102.07945 ；作者代码 https://github.com/s-h-yang/HFD
  - TL-HFD：Chaitanya, Dalleiger, Ruiz, 2026，https://arxiv.org/abs/2606.09340 （未找到作者代码；需按 Algorithm 1 复现，标记为 TL*）
  - CFSP：Bühler, Rangapuram, Setzer, Hein, ICML 2013，https://arxiv.org/abs/1306.3409
- 附件（由用户提供，可复用或重写）：
  1. local_hfd_package：早期探针与 4 张 LFR 图（graphs/<case>.graph.json 含 n、edges；<case>.truth.json 含 communities）。
  2. ZHFD_Research_Proofs_Code_Results.zip：上一轮代码（code/core.py 中的 flow_cd、best_sweep、unary_cut、ratio_refine；tl_graph.py；tests_math.py），12 张 NetworkX LFR 图及结果，证明笔记。
  3. review_round1/attractor_and_leiden.py/json：远处团测试与 Leiden 对照。
  4. theory/：理论方的小规模数值核验（checks_a.py 至 checks_g3b.py 及对应 JSON），以及 zr_pipeline.py——v1.2 流程的纯 Python 参考实现（networkx min-cut，不处理并列值）。它只用于 M0 对照，不是工程实现，也不是规格的一部分；与第 2 节冲突时以第 2 节为准。
- 已知事实（需复现，不需重新论证）：
  - 附件两张 μ=0.5 图上，HFD 质量网格 + Z-sweep + 全图 MM 精化（上一轮的 A∞）的 F1 中位数为 1.000 / 0.9965；Leiden 种子社团为 1.000 / 1.000。
  - NetworkX 的 LFR 生成器名义 μ 与实测 conductance 不一致（名义 0.5 → 实测约 0.71–0.73）。实验一律按实测真值 conductance 分组报告。
  - 在附件 μ=0.5 s11 图上加一个远处不连通的 K30：Z 的 seeded 全局最优离开真值社团（中位 Z(C∪K)=0.412 < Z(C)=0.563）；全图精化在 2/12 个查询中把 K30 并入，且是否并入取决于节点编号的打破平局。区域限制就是为了消除这个问题。
  - 12 个 SBM 实例（(K, s, p, q) ∈ {(4,100,.5,.05), (4,100,.3,.02), (5,80,.6,.05), (4,250,.1,.01)} 各 3 个，种子在真值社团内随机，numpy.random.default_rng(59)，脚本 theory/checks_g2.py、theory/checks_g3b.py）：v1 停止规则 12/12 输出 {s}；v1.2（P = 3）+ R-supp 精确恢复 10/12，平均 F1 0.994，最小 0.934，两个失败都在稀疏组，一个是 C ⊄ R、一个是 C ⊆ R 但差一个点；v1.2 + R-cap（θ = 1/2）精确恢复 6/12，平均 F1 0.860，6 个失败全部是 C ⊄ R；P = 2 + R-supp 精确恢复 10/12，平均 F1 0.925（一个稀疏实例提前停在小集合，F1 0.099）。
2. 冻结规格 v1.2（理论方负责；不得更改）
2.1 记号与目标
- 普通图 G=(V,E)，无向，先做无权（加权为可选扩展）。度 d，vol(S)=Σ_{u∈S} d_u，M=vol(V)，cut(S) 为 S 与 V∖S 之间的边数，e(A,B) 为 A、B 间边数，φ(S)=cut(S)/min(vol S, M−vol S)，φ_v(S)=cut(S)/vol(S)。
- 目标：Z(S) = cut(S)/vol(S) + vol(S)/M = N(S)/vol(S)，其中 N(S) = cut(S) + vol(S)²/M。
  Z = 1 − normalized modularity（Bolla 2011；Fasino–Tudisco 2017 §2）。这不是新目标，任何文档都不得声称它新。
- 超图主目标 Z_H（期望割零模型）：超边 e 带权 θ_e 与分割函数 w_e（只依赖 |T∩e| 的计数 j，w_e(0) = w_e(|e|) = 0；全有或全无即 0 < j < |e| 时 w_e = 1）。d_u = Σ_{e∋u} θ_e，M = Σ_e θ_e·|e|，C(S) = Σ_e θ_e·w_e(|S∩e|)。
  Ψ(v) = Σ_e θ_e·E[w_e(J_e)]，J_e ~ Binomial(|e|, v/M)；G(v) = v − Ψ(v)；Z_H(S) = [C(S) + G(vol S)]/vol(S)。
  Ψ 按超边规模分组预计算；w_e 与 HFD 使用同一分割函数；w_e 不满足 w_e(j) ≤ min(j, |e|−j) 时先归一化并在报告中注明。普通图上 G(v) = v²/M，Z_H 退化为 Z。
- 超图变体 ZH-prov（v1 的暂定版）：Z_H^prov(S) = C(S)/vol(S) + vol(S)/M。|e| ≤ 3 时两者相同。
2.2 主方法 ZR-HFD（四步）
Step 1　不依赖体积的质量倍增扩散
- 质量序列 m_j = m_0·2^j，m_0 = 3·d_s，j = 0, 1, …
- 对每个 m_j 求扩散对偶解 x_j：min_{x≥0} ½Σ_e θ_e f_e(x)² + (σ/2)Σ_u d_u x_u² − ⟨Δ−d, x⟩，Δ = m_j·e_s，σ = 1e-4，f_e 为 w_e 的 Lovász 扩展。普通图即 ½xᵀLx + (σ/2)xᵀDx − ⟨Δ−d, x⟩。超图与 HFD 原文一致；若作者代码的目标与此不同，记录差异。
Step 2　Z-sweep 与停止规则
- S_j = argmin{ Z(L) : L 是 x_j 的含种子水平集，且不切开取值并列的块 }（超图用 Z_H）。
- 记 j_act = 第一个满足 |supp(x_j)| ≥ 2 的 j。
- 停止：(a) m_j > M/2（该质量不再计算）；或 (b) j ≥ j_act 之后，连续 P = 3 次倍增都没有使最优 Z 下降超过 ε = 1e-6（j_act 之前的不改进不计数）。
- 若到预算仍未激活，输出 {s} 并标记 no_activation。
- 取 j* = argmin_j Z(S_j)，记 S⁰ = S_{j*}。
Step 3　区域
- 主规则 R-supp：R = supp(x_{j*+1})；若 j*+1 尚未计算则补算一次（可以超过 M/2）。
- 变体 R-cap(θ)，θ ∈ {1/4, 1/2, 1}：R = S⁰ ∪ L，L 是 x_{j*+1} 的最大水平集（不拆分并列块）且 vol(L∖S⁰) ≤ θ·vol(S⁰)。
- 断言 s ∈ R 且 S⁰ ⊆ R；若断言失败，按第 0 节"矛盾现象"处理。
Step 4　区域内 MM 精化（k = 0, 1, …）
- λ_k = Z(S^k)。
- 排序 π_k：先排 S^k（种子第一，其余按 x_{j*+1} 降序，再按节点编号），再排 R∖S^k（按 x_{j*+1} 降序，再按编号）。R 外的节点不参与排序。
- g^k_i = D_i² − (D_i − d_i)²，其中 D_i 为 π_k 中排到 i 为止的累积度。超图用 g^k_i = G(D_i) − G(D_i − d_i)。
- u^k_i = g^k_i/M − λ_k·d_i（超图：u^k_i = g^k_i − λ_k·d_i，因为 G 已含 1/M 的尺度）。
- S^{k+1} = argmin{ cut_G(S) + Σ_{i∈S} u^k_i : s ∈ S ⊆ R }。cut_G 按全图计算，从 R 指向 R 外的边一律算作被割；用精确 s-t min-cut 求解（可乘公分母转成整数容量）。超图用精确割归约。
- 若 Z(S^{k+1}) < Z(S^k)（用整数交叉相乘判断，不用浮点比较），接受并继续；否则停止，输出 S^k。
输出与证书：S_final；每步 min-cut 的最优值；所用质量序列、j_act、j*、普通图的 m_act；vol(R)；实际触及的体积（各次扩散支撑 ∪ 区域）；区域下界 LB_R（在 R 上做参数化 seeded min-cut，取 {(vol T, cut T)} 的下凸包，LB_R = min_v [ĉ(v) + v²/M]/v，超图把 v²/M 换成 G(v)）；gap = Z(S_final) − LB_R；hull-best（凸包顶点中 Z 最小者，作为变体输出）；间隙界遥测 max_i (v_{i+1} − v_i)²/(4M·v_i)（普通图）。
2.3 命题（证明由 Claude 负责；你负责数值核验）
记号：U = supp(x)；pen_R(T; C′) = 2[vol(C′∩T)·vol(T∖C′) + vol(C′∖T)·vol(R∖C′)] / (M·vol C′)。
- P1 conductance 的合并偏置：vol(A∪B) ≤ M/2 时，φ(A∪B) = [vol A·φ(A) + vol B·φ(B) − 2e(A,B)] / (vol A + vol B)。
- P2 Z 的合并判据：Z(A∪B) = [vol A·Z(A) + vol B·Z(B) − 2(e(A,B) − vol A·vol B/M)] / (vol A + vol B)。
- P3 单点判据：Z(A+u) < Z(A) ⟺ e(u,A) > (d_u/2)(1 − Z(A)) + d_u·vol(A)/M + d_u²/(2M)；删除版本同理（把 A 换成 A∖{u} 后取反）。
- P4 精确松弛与 sweep 证书：对 x ≥ 0 且 x_s = max_i x_i，令 H(x) = Σ_i x_{π(i)}(D_i² − D_{i−1}²)（π 使 x 降序），𝒵(x) = [TV(x) + H(x)/M] / dᵀx。则 min_t Z(S_t(x)) ≤ 𝒵(x)，且 min_x 𝒵(x) = min_{S∋s} Z(S)。
- P5 MM 步的正确性：在 S^k 处子问题目标值恰为 0；子问题出现负值 ⇒ Z 严格下降；因此 Z 单调不增。
- P6 非局部性（一般形式）：C ∋ s，K 与 C 不相交且不相邻，则 Z(C∪K) < Z(C) ⟺ φ_v(C) − φ_v(K) > (vol C + vol K)/M。推论：只读取种子邻域的算法无法认证全局 seeded Z 最优。
- P7 区域证书与局部性：S_final ⊆ R；在 R 内对所用上界函数为 MM 驻点（最后一次 min-cut 最优值为 0）；对精确解有 vol(R) ≤ m_{j*+1}（普通图与超图均由 V(c) 给出）。这是 MM 驻点证书，不是 R 内全局最优证书；全局部分由 LB_R 与 gap 给出。
- P8 均值 SBM 分离：块数 K 为偶数且 ≥ 4，每块 s 个点，块内权 p、块间权 q > 0，δ = (s−1)p + (K−1)sq。则对每块计数 a_j、t = Σa_j，有 Z(S) = 1 + p/δ − ((p−q)/δ)·Σa_j²/t + (1/(Ks) − q/δ)·t。当 (s−1)p > sq 时，seeded Z 的最小者唯一等于种子所在块，而 conductance 的最小者是含种子块的 K/2 个整块之并。
- V 变分支撑引理（普通图与一般超图，精确求解）：(a) x_s = max_u x_u；(b) U 的每个连通分量（超图上按"共处一条超边"连通）都含 s；(c) vol(U) ≤ m，且 m − vol(U) = Σ_e θ_e·f_e(x)·w_e(|U∩e|) + σ·Σ_{u∈U} d_u x_u（普通图右端第一项即 Σ_{u∈U, v∉U} w_uv x_u）。
- Mono 质量单调：普通图与全有或全无超图上，m ≤ m′ ⇒ x(m) ≤ x(m′) 逐点成立（从而支撑嵌套）。cardinality-based 超图（|e| ≥ 4）未证，只记录违例。
- A 首次激活（普通图）：supp(x(m)) = {s} ⟺ d_s < m ≤ m_act。
- Leak 种子邻居泄漏（普通图）：x_s ≥ (m − d_s)/((1+σ)d_s)；凡 d_v < w_sv(m − d_s)/((1+σ)d_s) 的种子邻居 v 都在 U 内。
- T-c 与 T-c′：LB_R ≤ min{Z(T) : s ∈ T ⊆ R} ≤ hull-best；普通图上 LB_R ≥ hull-best − max_i (v_{i+1} − v_i)²/(4M·v_i)。
- FP 不动点不等式：设 S_f 是排序 π_f 下的 MM 不动点。对 R 内任意含 s 的集合 C′：Z(S_f) − Z(C′) ≤ 2Σ_{i∈C′} d_i·vol(π_f[1..i]∖C′)/(M·vol C′) ≤ pen_R(S_f; C′) ≤ 2vol(R∖C′)/M。（不需要真值，可对任意 C′ 检验。）
- MM-exact：对 R 内含 s 的 C′，若对 R 内所有含 s 的 T ≠ C′ 都有 Z(T) − Z(C′) > pen_R(T; C′)，则任意排序、任意起点的 MM 不动点都等于 C′。
- M′ 超集间隙（均值 SBM）：T ⊇ C 时 Z(T) − Z(C) ≥ (1/(Ks) − q/δ)·b，b 为 T 中块外点数；b ≤ s/2 时 ≥ ((p−q)/(3δ) + 1/(Ks) − q/δ)·b。
- T-b 超图零模型：G 凸；|e| ≤ 3 时 G(v) = v²/M（与 ZH-prov 相同）；合并式 Z_H(A∪B) = [a·Z_H(A) + b·Z_H(B) − R(A,B) + G(a+b) − G(a) − G(b)] / (a+b)，其中 R(A,B) = C(A) + C(B) − C(A∪B)，a = vol A，b = vol B。
3. 工程自主范围（由你决定，只需记录理由）
- 扩散求解器：用作者代码，或自写后在小实例上与作者代码核对目标值，二选一。断言只在高精度模式下执行；近似求解时只记录违例与缩放 KKT 残差、质量守恒残差，不中止。
- TL*：按 TL-HFD 的 Algorithm 1 和论文默认参数复现，记录与原文的所有差异。
- max-flow / min-cut 与参数化 min-cut 的实现与语言（C++ / Rust 扩展、numba、现成库均可）；超图割的精确图归约（全有或全无用 Lawler 构造，cardinality-based 用 Veldt–Benson–Kleinberg 归约，或你认为更好的等价构造）。
- 数据生成器与下载脚本：带校准混合度的 LFR（原版 C++ 生成器或 ABCD 均可）、SBM 与超图 SBM 生成器；需记录参数与校验和。
- 并行、缓存、数值容差、日志格式、绘图。
- 在 dev 图上探索改进主方法的变体（排序方式、多起点、区域放大倍数等），必须另起名字，不得替换主方法。
4. 里程碑与验收（按顺序执行；每个都写入 REPORT.md）
- M0 复现：
  - 附件两张 μ=0.5 图上全图 MM 精化的结果（逐查询的 F1 与 Z 一致，或差异可解释），以及远处团测试的 2/12。
  - 用 theory/checks_g2.py、theory/checks_g3b.py 的同一批 12 个 SBM 实例复现第 1 节最后一条：v1 停止规则输出 {s} 的个数、v1.2 在 R-supp 与 R-cap 下的精确恢复数与 F1。你的工程实现与参考实现的差异要逐条解释（并列值处理、min-cut 精度等）。
- M1 理论核验测试集（tests/）：
  - §2.3 的全部命题：n ≤ 14 枚举所有含种子子集；随机加权图；随机超图（全有或全无与 cardinality-based 各一组）；扩散用高精度求解。
  - P5：每一步的零值与单调性。FP 与 MM-exact：对 R 内每个含种子的 C′ 检验。
  - 诊断（不是关卡）：|R| ≤ 22 时穷举 R 内含种子子集，统计 MM 输出与区域内真最优的差距。
  - 验收：0 违例（cardinality-based 超图的 Mono 只记录）。
- M2 ZR-HFD（普通图）：实现 Step 1–4 与证书。验收：
  - 远处团测试在两种节点编号放置下、R-supp 与 R-cap 两种区域下都是 0/12 并入，且 F1 相对无团情形下降不超过 0.01；
  - 回归检查：报告所有 |S_final| = 1 的查询及其 j_act、m_act；不得出现 v1 那种"未激活就停机"的输出；
  - 附件两张 μ=0.5 图上，F1 中位数相对全图版本的差值如实报告。
- M3 数据与基线：
  - 校准 LFR / ABCD：实测混合度 {0.1, 0.2, 0.3, 0.4, 0.5, 0.6}；n ∈ {1000, 10000}；每档 3 个生成种子。
  - SBM：K ∈ {4, 8}，稠密一组（p、q 为常数，取第 1 节的三组参数）与稀疏一组（p = 0.1、q = 0.01）；每组 3 个生成种子。
  - dev / test 划分预先固定：dev = 附件 4 张图 + 12 张 NetworkX 图 + 上述 SBM；test = 新生成的校准 LFR / ABCD 图，生成一次后冻结，只用于最终评估，不得用于任何调参。
  - 基线：HFD、TL*、ACL、p-norm flow diffusion（如 LocalGraphClustering 包）、Leiden（全局对照，取包含种子的那个社团）；CFSP 可选，若做则给真实体积上下界，并标明使用了 oracle。
  - 每个局部基线跑两种设置：不给体积（质量网格或倍增 + conductance sweep，作为主设置）；给真实体积（参考设置，明确标注 oracle）。
- M4 普通图主实验：
  - 每个查询记录：F1、precision、recall、Z(out)、φ(out)、vol(out)、|out|、输出的连通分量数、Z(truth)、运行时间、触及体积、j_act、j*、m_act、LB_R、gap、hull-best 的 F1、间隙界遥测、证书状态。
  - 汇总：中位数与均值（附 bootstrap 置信区间），按实测混合度分组；每个种子与 Leiden 种子社团的 F1 差值。
  - 消融：
    - 区域：R-supp（主）、R-cap(θ)（θ ∈ {1/4, 1/2, 1}）、supp(x_{j*})、supp(x_{j*+2})、全图；
    - 停止规则：耐心 P ∈ {2, 3}；变体 ZR-mact（普通图，m_0 = m_act·(1+10⁻⁹)，耐心从 j = 0 计数）；
    - 质量调度：倍增、√2 网格、固定网格；
    - 预算：M/2（主）与 M（变体 ZR-budgetM）；
    - R 内排序：扩散分数 / BFS 距离 / 随机，以及多起点取 Z 最小；
    - Step 1 的求解器：HFD vs TL*；
    - 关闭精化（只做 Z-sweep）；hull-best 代替 MM 输出；
    - 把 Z-sweep 换成 conductance sweep。
  - 带真值的诊断（只用于分析，不进入任何选择或调参）：覆盖指示 [C ⊆ R]；ρ̂ = max_{j≠0} |R ∩ C_j|/|C_j|；vol(R∖C)/vol(C)；首次覆盖质量 m_c（对 m 二分求 C ⊆ supp(x(m)) 的最小质量）与 m_{j*}、m_{j*+1} 之比；单步间隙余量（对 u ∈ C∖s 的 Z(C∖u) − Z(C) − pen_R(C∖u; C)，对 v ∈ R∖C 的 Z(C∪v) − Z(C) − pen_R(C∪v; C)）；输出的 |TΔC|。每个失败查询归入 H1（C ⊄ R）或 H2（C ⊆ R 但输出 ≠ C），与 F1 交叉列表。
- M5 超图：
  - 实现：超图扩散（或用作者代码）、Z_H sweep（主）与 ZH-prov sweep（变体）、用精确超图割归约的区域内 MM 精化（全有或全无与 cardinality-based）、区域下界。
  - 数据：合成超图 SBM；contact-high-school；Trivago-clicks（按 TL-HFD 协议，10 个簇 × 每簇 100 个单种子查询）；Amazon 可选。可从 Benson 数据仓库（cs.cornell.edu/~arb/data）等来源获取。
  - 基线：HFD（作者代码）、TL*、LH-p（可选）、ACL（在 clique expansion 上跑）。
  - 主表只放全有或全无；cardinality-based 的结果标注"单调性未证"。
- M6 规模与局部性：
  - 数据：n ∈ {10^4, 10^5, 10^6} 的校准生成图，或带真值社团的真实大图（如 SNAP 的 com-DBLP、com-Amazon）。
  - 报告运行时间、触及体积 / vol(out) 随 n 的变化。社团规模固定时，触及体积应基本不随 n 增长；给出拟合斜率。
5. 预先登记的关卡、区域规则与停止条件
关卡	判据
G-E0	M1 零违例。违例即硬停受影响部分，并写入 THEORY_REQUESTS.md
G-E1	远处团测试在两种编号放置、两种区域下均 0/12 并入，F1 下降 ≤ 0.01
G-E2（test 图，实测混合度 ≤ 0.5）	单种子 F1 中位数 ≥ Leiden 种子社团中位数 − 0.03；且在实测混合度 ≥ 0.4 时 ≥ HFD（不给体积）+ 0.10
G-E3	触及体积 / vol(out) 的中位数 ≤ 20，且运行时间随 n 次线性增长（报告斜率）
G-E4（超图）	至少一个真实数据集上，F1 中位数 ≥ HFD（不给体积），并报告与 HFD（给体积）的差距


- 区域主规则的预登记比较：在 dev 图（附件 4 张 LFR）与 M3 的 SBM 上，R-supp 与 R-cap(1/2) 用同一组种子做配对比较，报告 F1 差（R-cap − R-supp）的配对 bootstrap 95% 区间。若区间下界 > 0，主规则改为 R-cap，并在 REPORT.md 写明；否则保持 R-supp。这一比较不得使用 test 图。
- G-E2 未通过时：只在 dev 图上诊断（未激活或过早停机、C ⊄ R、C ⊆ R 但 MM 未停在 C 三类原因分开统计），写入 THEORY_REQUESTS.md。不得用 test 图调参，不得删除失败的图或查询。
6. 禁止事项
- 方法路径中使用真值（明确标注的 oracle 参考组与 §4 的诊断除外）。
- 修改第 2 节；以变体之名悄悄替换主方法。
- 声称新颖性、声称定理已证明，或自行撰写证明（证明归理论方）。
- 删除失败结果；结果没有固定的随机种子；任何依赖 GPU 的工作。
7. 交付物与目录
zrhfd/           核心包（扩散、sweep、区域、MM、min-cut、参数化 min-cut、超图归约、证书）
tests/           M1 理论核验与单元测试
experiments/     配置（yaml）与运行脚本；每个里程碑一条复现命令
data/            生成与下载脚本、校验和（大文件不入库）
results/         逐查询原始 JSON + 汇总 CSV
figures/
REPORT.md        每个里程碑：做了什么 / 证据表（数字 + 置信区间）/ 关卡状态 / 决策记录 / 未决问题
THEORY_REQUESTS.md  需要理论方裁决的问题、反例的最小复现、有证据支持的建议
CHANGELOG.md
报告用中文，保留英文术语与代码标识符。
8. 理论方尚未完成的事项（不要等待，按本规格推进）
- H1：有限样本下 C ⊆ R 的条件（覆盖质量与 j* 的位置）。稠密渐近情形理论方已证，其中一个条件是局部性 m_c < M/4；K = 4、5 的 SBM 不满足它，此时能否覆盖取决于网格是否恰好落在 M/2 之内，所以这些实例请同时报告 ZR-budgetM。请收集：各 regime 下 [C ⊆ R] 的频率、m_c/m_{j*} 的分布、首次覆盖前后支撑中块外点的体积。
- H2：MM-exact 的间隙条件在有限样本中一致成立的条件。请收集：单步间隙余量的分布、H2 类失败的最小例子。
- H3：稀疏区（sp² 小）的覆盖与恢复。请收集：稀疏 SBM 中 sweep 提前停在小集合的频率与对应的 Z 轨迹。
- H4：cardinality-based 超图的质量单调性。请收集：任何 Mono 违例的最小超图实例。
- H5：全图 seeded Z 的种子不一致（P6′）。可选：在 SBM 中统计全图最优 ≠ C 的比例随 s/δ 的变化。
工程上遇到与这些相关的证据，请整理进 THEORY_REQUESTS.md。