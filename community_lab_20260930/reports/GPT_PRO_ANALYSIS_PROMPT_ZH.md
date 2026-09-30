你是独立研究分析者。请先读本包FINAL_REPORT、CANDIDATE_DECISION、FAILURE_MAP和BASELINE_REPORT，再查analysis/results.csv、nocd_pairdot_gate_v1的strata/pairs/update_counts/cap1000/gate-analysis及candidate_profile_summary。不要把文献成绩当本轮结果，不要用另一个proposal取代对实际瓶颈的分析。

固定任务是普通无向无权、只用拓扑、全图重叠社区检测；native-K与oracle-K分开。已有576正式任务，564完成并评分，12 BigCLAM auto-K/n5000超时未知。C1仅改NOCD sampled pair-dot primitive，比较elementwise/BMM/CSR及elementwise cap1000。所有CPU线程设置1、测量串行、完整pipeline计费；真实label不进入算法。确认图未生成/使用。

关键实际事实：CSR n5000对elementwise三算法seed中位节时18.4766%/17.1480%/17.4531%，同更新数36/36，训练forward/backward每更新约节省20%–22%；但n1000三seed慢7.3%–7.9%，seed75 macro平均差−0.0108144000793未达事前−.01门槛。BMM平均质量合格但六层全部变慢。CSR小图有5项材料退化，大图也有至少两正确归属召回下降，对BMM有一项macro下降−.036739。冻结gate关闭，不得把接近阈值改成通过。cap1000使大图时间约1.8–1.9倍，macro变化很小且方向不一致。BigCLAM/oracle-K在大图12/12同图上比原NOCD更快且macro/micro更高；不同实现栈的实用对照不能隔离算法复杂度。

请给出证据驱动的分析：
1. 哪些结论可以从表与trace直接得出，哪些只有相关性？首先找出最早归属信息丢失阶段或真正耗时位置，指出目前根因证据还缺什么。
2. C1小图质量漂移更可能在哪个环节发生？数学等价、同初始embedding、同更新数分别能和不能排除什么？提出最少且不使用label决策的判别实验；不要先指定一个“必然有效”修复。
3. 判断是否存在值得另开一轮测试的一个单机制；如有，明确改动、可被数据否定的预测、最强适用竞争者、简单增加预算与已有修复控制。若没有，明确推荐维持负面结论。不要组合同时换初始化/传播/损失/解码的多机制。
4. 区分后端工程加速、全方法质量—成本前沿与研究novelty。给出一句话insight，但不得命名已知恒等式为新定理。需要检索先例时请检索公开关键词与原论文/官方源码，标明依据。
5. 如建议下一轮，必须先冻结新预算/协议，使用新的开发/确认分工；不可把当前准入失败的数据改名确认，不可根据case_id、真overlap或分数路由后端，不可用训练loss/modularity替代归属恢复。禁止quota/CB/PL、BCSU、安全收缩、residual fission、恢复阈值或自动换题。

输出采用“已知事实—尚不支持的归因—最小判别实验—继续/停止决定”，并引用具体文件与case/seed。没有赢家是合法结果；不要为了达到顶会预设而放宽证据。
