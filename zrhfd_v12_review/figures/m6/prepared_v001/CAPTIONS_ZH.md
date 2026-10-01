# M6 图注与口径

所有图只用 `results/m6_prepared` 的固定108-query cohort，不引入旧实现结果。每档三个独立生成图、36个预定query。失败、超时、未运行均留在CSV与分母图。

`scale_hot_cost_and_touched_ratio`：完成query的实际算法hot wall与触及/输出volume；黑菱形为各图完成子集的中位数。hot包含完整扩散、sweep、MM、区域证书和checkpoint写入，不含预热/输入加载/离线真值评价。completed-only logn斜率与图级bootstrap只描述完成子集；存在删失时不据此宣布G-E3通过。横虚线20为登记关卡值。数学支撑volume不是全部内存/IO访问的计量。

`quality_vs_hot_cost`：每个完成query的实际F1与hot时间，包括快速但质量低的输出。没有将低质量快例包装为同质量加速。

`process_clock_censoring`：完成query的parent总时钟，与timeout/memory-limit的观测时钟分别绘制。空心上三角表示删失下界，包含启动/预热等；它不是hot完成时间，也不属于completed cohort。方法产物可能部分完成，也可能在完整方法证书保存后、离线评价或序列化时截断，须按原始阶段与文件另列，不能统一宣称没有证书。

`completion_denominators`：全部108任务的最新attempt状态，原中断attempt仍保留在raw目录，不重复当成独立query。

SVG/PDF是可导出的矢量图，PNG供视觉核验。若最终仍有未完成任务，所有图和斜率明确为partial/completed-only，不补造结果。
