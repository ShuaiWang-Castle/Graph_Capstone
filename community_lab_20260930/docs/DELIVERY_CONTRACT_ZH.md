# 运行、文件接口与交付

## 标准输入输出

图：`{"n":5,"edges":[[0,1],[1,2]]}`。节点全集0..n-1，edges每条u<v，不含重复/loops，不能从最大边ID推断n。

预测：`{"communities":[[0,1],[1,2]],"metadata":{},"stage_seconds":{}}`。

真标签：独立`evaluation_only`目录中的同格式对象，完整生成标签另有`"labels_complete":true`。该字段不得因为希望使用strict evaluator而对真实metadata强行设true。

适配器命令只接收graph、output、seed、config；不接收truth。checkpoint通过LAB_CHECKPOINT写出。config可含oracle_K，但必须进入独立的信息面板。

`configs/methods.json`是初始参数方案。宿主先smoke，确认实际API/版本后冻结；不能观察开发或确认得分后悄悄改变native defaults。未知字段导致明确失败，不默默fallback到不同算法。

## 运行计划

prepare_plan保存所有jobs和精确config、graph及适配器代码hash。每个job目录内：
- spec.json：原始不可变任务；
- stdout.log、stderr.log：真实进程日志；
- prediction.json：正常返回cover；
- checkpoint.json：预算未完成时的最后合法快照；
- result.json：wall、RSS、返回状态及文件hash；
- 原生工具输出：保留足以复核转换的文件。

必须给同一新版本使用新的job_id/计划目录，不能覆盖失败和旧指标；也不能无说明反复重跑到成功。恢复不完整attempt时，先原样归档并记录已花成本，再新建attempt。run_jobs检测到同ID残留半成品会停止，避免悄悄读取旧输出。

新增方法适配器遵守同接口，最初不得替换掉baseline；候选以明确的新名字出现。详细阶段trace可新增stage_trace.jsonl/arrays，避免重复收集未使用的巨量dense F快照。

## 必须输出

```
reports/
  BASELINE_REPORT_ZH.md
  FAILURE_MAP_ZH.md
  CANDIDATE_DECISION_ZH.md
  FINAL_REPORT_ZH.md
analysis/
  results.csv
  results.json
  per_job/
  quality_cost_<policy>_<device>.png
provenance/
  SOURCE_LOCK.json
  dependency_versions.txt
  protocol_freeze.json
  patches/
RESUME.md
DELIVERY.zip
```

文件名可以按工作区整理，但不能只报不可访问内部路径。Claude环境若下载入口为outputs，应复制到可下载目录；Codex/本地机器则保存明确的相对工作区路径。不要假装已经上传到ChatGPT。

打包保留代码、配置、原始预测、关键日志、哈希、失败和简洁报告。第三方论文、巨大虚拟环境、编译对象和冗余缓存不打包；公开数据大文件可附来源+哈希+取得脚本。未经授权的私有原图不上传。

## 报告里必须有的两句话

“本轮实际执行了哪些任务，未执行了哪些任务；确认集有没有参与调参。”

“观察到的改善来自什么具体步骤；哪些结果只证明工程收益，哪些还需要理论或先例核查。”

NO_REPRODUCIBLE_GAIN是合法产物，不能为了避免这个状态而修改目标或只展示赢家。
