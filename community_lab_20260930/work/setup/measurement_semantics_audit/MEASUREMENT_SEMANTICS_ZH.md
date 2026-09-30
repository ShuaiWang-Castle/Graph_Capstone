# 成本与内存记录口径

本次只审源码及初始基线 24 项已完成 Highway native 的 result metadata。没有读取 C1 质量、真标签或 scoring 文件，没有重测、profile 或修改原件。逐项行号、源码 SHA 和原 metadata SHA 在 `MEASUREMENT_SEMANTICS_EVIDENCE.json`。

## 时间

`pipeline_seconds` 实际从 runner 的 `perf_counter()`（lab/runner.py:69；在输入/配置/源码 hash 和参数准备之后、日志打开/Popen 之前）到专用 wait 线程观察 `p.wait()` 返回后（73–77）结束。它是**新适配器进程的墙钟到退出**，比“最后 cover 写出时刻”多包含进程退出/清理和 wait 线程调度延迟；不受原约0.2s polling 的观察地板量化。

包含 child 的 import/load、预处理/输入转换、训练、model selection、decode、checkpoint/cover 写出，以及 child 实际等待的 native 子程序。Highway/BigCLAM adapter 使用阻塞 subprocess.run（adapters/run.py:103、123），因此这些 native 子程序的工作包含在主墙钟内。adapter 内部 provenance/source/binary 哈希也属于其进程工作并被计入。

不包含外层 runner 的 import、preflight 输入/源码哈希（48–68）、退出后的 graph/cover 合法性验证与 prediction SHA（121–123）、result.json 保存（128），以及安装/下载/编译、离线真标签评分。`evaluation_seconds` 是 summarize.py:25–42 的独立计时，包含 offline hashes、标签读取、score 和 per_job 证据写入。不能将“所有 hash 均免费”作为表述，因为 child 内部 hash 已计入。

`monitor_elapsed_seconds` 是主监控循环收尾到113行的另外一个观察值，不能替代主 pipeline。`p.wait()` 等直接 child；一般 adapter 等 native 子程序，但 runner 不独立等待已脱离/遗留的任意后代。

TIMEOUT/MEMORY_LIMIT 的 `pipeline_seconds` 可能包含 SIGTERM 后至多3秒的等待及 SIGKILL 收尾（7–17、95–96），会超过名义预算；它不是成功完成时间。`budget_seconds`、status 与实际 elapsed 要分别列出。未启动的 BLOCKED/NOT_RUN_BUDGET 中0秒是“未执行”标记，不是算法成功耗时。

建议表头：**适配器进程墙钟至退出（s，含导入与输出写入）**；超时单独列状态和实际支出。

## 内存与限制

`peak_tree_rss_bytes` 是每次递归枚举 adapter 及当前 descendants，将 psutil.memory_info().rss 相加并取**最大观测值**（83–99、117）。root 的监控进程不在其中。采样 wait 最多约0.2s，实际间隔还包含查询、日志检查和调度；逐进程读数也不同步。共享页可能重复计数，已退出/不可访问进程会被跳过，短瞬时峰值或整个短子程序可漏采。它不是 OS 精确高水位、PSS/USS、唯一物理 RAM 或 GPU memory。

`memory_mb` 在代码中乘1024²，因此当前1500表示1500 **MiB**。守卫对采样历史 peak > 阈值后才终止进程组（96）；没有设置 OS hard RLIMIT/cgroup allocation cap。瞬时超限可漏检，共享页重复计数也可偏大；94行先检查进程已退出，快任务可能完成后不再处理该采样超限。应称**采样 RSS 监控与软终止阈值1500MiB**，不能称“操作系统硬内存限制”或“成功即从未超限”。

初始 Highway native 24项完成，墙钟范围0.1251–0.2839s，中位数0.1862s；19项短于0.2s。15项最大观测RSS仅245760 bytes（0.234375MiB），20项小于1MiB；全部记录绑定相同已审 runner SHA。源代码能解释采样覆盖不足的风险，但没有 sample count/history，不能确定每个例子具体只看到了哪个阶段，不能恢复真实峰值。

这些原值应保留并可披露为**观测到的采样 RSS**。它们不能支持“真实峰值只0.234MiB”、内存优胜或可靠跨方法 RAM 排名；不要删除短例，也不要估填一个更可信峰值。内存表标注 **underresolved / 短运行采样不足**，并明确真实峰值 UNKNOWN。

`sampled_tree_cpu_seconds` 同样是当前可见进程树累计 user+system CPU counters 的采样最大和，不是全程积分 CPU usage；退出子程序的计数可消失，尤其短 native 任务不可当精确 CPU 成本。

## 线程

`threads` 和六个 `thread_environment` 是请求配置（52–65）。NOCD 还调用 torch.set_num_threads（adapters/nocd_graph_only.py:28），BigCLAM传 -nt（adapters/run.py:119）；Highway metadata 声明此次编译 serial/OpenMP不可用。它们是代码/API/环境约束，不是 OS 观测。

没有记录运行时 OS num_threads、CPU affinity、core occupancy 或完整线程 history；数值库设置也不等于每个进程只有一个 OS thread。报告可写**CPU、数值计算线程配置为1；OS实际线程数未测量**，不能声称“一核硬隔离”或“系统观测证实只有1线程”。root 的监控 wait 线程不属于被采样的算法进程。

本轮无需为上述口径重跑算法。正式报告如实使用墙钟与采样指标，保留未知和软限制边界即可。
