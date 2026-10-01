"""Update scale-data engineering report from measured records, retain failures."""
import csv
import json
from pathlib import Path
import numpy as np
from scale_storage import sha

ROOT=Path(__file__).resolve().parents[2]
def main():
    catalog=json.loads((ROOT/"data/scale/catalog.json").read_text());cfg=json.loads((ROOT/"experiments/data_generation/scale_config.json").read_text())
    rows=[];query_rows=[]
    for r in catalog["cases"]:
        m=r.get("statistics",{});sizes=m.get("community_sizes",[])
        rows.append({"case_id":r["case_id"],"n":r["n"],"status":r["status"],"attempt_count":r["attempt_count"],"generation_seconds":r.get("generation_seconds"),
                     "conversion_seconds":r.get("conversion_seconds"),"load_verify_hash_seconds":r.get("load_verify_hash_seconds"),"native_max_rss_bytes":r.get("native_max_rss_bytes"),
                     "controller_cumulative_max_rss_bytes":r.get("controller_max_rss_bytes"),"csr_arrays_bytes":r.get("csr_arrays_bytes"),
                     "weighted_truth_conductance":m.get("weighted_truth_conductance"),"mean_degree":m.get("mean_degree"),"max_degree":m.get("max_degree"),
                     "min_community_size":min(sizes) if sizes else None,"max_community_size":max(sizes) if sizes else None,"query_count":r.get("query_count",0),
                     "community_size_outliers":sum(s<cfg["community_bounds"][0] or s>cfg["community_bounds"][1] for s in sizes),
                     "community_count":len(sizes),"community_size_quantiles":json.dumps(np.quantile(sizes,[0,.25,.5,.75,1]).tolist()) if sizes else None})
        if "queries_path" in r:
            for qi,q in enumerate(json.loads((ROOT/r["queries_path"]).read_text())["queries"]):
                ci=q["community_index"];size=sizes[ci]
                query_rows.append({"case_id":r["case_id"],"n":r["n"],"query_index":qi,"seed":q["seed"],"community_index":ci,"truth_size":size,
                                   "truth_volume":m["truth_volumes"][ci],"truth_cut":m["truth_cuts"][ci],"truth_conductance":m["truth_conductance"][ci],
                                   "truth_size_outlier":not cfg["community_bounds"][0]<=size<=cfg["community_bounds"][1]})
    out=ROOT/"results/data_generation"
    with (out/"scale_statistics.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    if query_rows:
        with (out/"scale_query_statistics.csv").open("w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(query_rows[0]));w.writeheader();w.writerows(query_rows)
    lines=["# M6 规模数据与 CSR 存储工程","","仅生成数据、验证存储；本任务未运行算法 quality。","",
           f"当前 catalog 完成 {len(rows)}/9 个目标输入；CALIBRATED {sum(r['status']=='CALIBRATED' for r in rows)} 个。固定配置先于实际 native 运行写入，SHA `{sha(ROOT/'experiments/data_generation/scale_config.json')}`。","",
           "参数为 n=10⁴/10⁵/10⁶、每档 seeds 202610061/62/63；native -k20/-maxk100、社区 size100…200、目标加权真值 φ=0.3。最多3次 native 尝试，每次900秒，native进程组RSS监控上限12GiB。每图独立重置 query RNG20261006，抽6社区×2单种子。所有原生输入、错误、失败 raw 与 stdout/stderr 保留。","",
           "| case | status | native 秒 | CSR 转换秒 | hash verify+load 秒 | native peak RSS MB | φ |","|---|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        def fmt(v):return f"{v:.4f}" if isinstance(v,(float,int)) else "—"
        lines.append(f"| {r['case_id']} | {r['status']} | {fmt(r['generation_seconds'])} | {fmt(r['conversion_seconds'])} | {fmt(r['load_verify_hash_seconds'])} | {fmt(r['native_max_rss_bytes']/1e6 if r['native_max_rss_bytes'] else None)} | {fmt(r['weighted_truth_conductance'])} |")
    lines += ["","数据是两遍流式读取 network.dat 后生成的 CSR，逐行排序去重并用稀疏二分查找核验对称性；没有构造 n×n 矩阵或 Python 全边表。indptr=int64、indices=int32、weights/degree=float64，四文件均为 .npy memmap。","",
              "`zrhfd.storage.load_csr(directory, verify_hashes=False)` 返回原 Graph 接口，全部数组为 readonly mmap，`edges` 为 lazy upper-edge iterable。degree 总和精确给 total；无权整数数据 `integer_weights=True`。未修改根 Graph/core。","",
              "小图交叉检查见 results/data_generation/scale_storage_validation.json：1000 个节点邻居、25 个子集的 Graph.stats、lazy edges、canonical JSON graph SHA 与 Graph.load 全部相同；readonly int32/int64/float64 CSR 已通过 NumPy/Numba 接口检查。","",
              "上表 load 包含四文件 SHA 校验，不是纯加载时间；controller 最大RSS是顺序控制进程的累计峰值。纯加载的独立进程测量由 scale_load_benchmark.py 产生，未迭代lazyedges、未调用算法；系统文件缓存不受控。native peak RSS 来自 macOS /usr/bin/time -l 的实际峰值，单位bytes。","",
              "初版资源wrapper误用了macOS拒绝的RLIMIT_AS=12GiB，27次preexec均失败，原生生成器一次也未启动。全部原记录/配置/日志保存在 data/scale/preflight_failure 与 results/data_generation/scale_preflight_failure.*。修复为RSS进程组监控后重新冻结资源配置；图生成参数/种子/选择规则不变，失败不删除，也不把未启动wrapper计作有效native尝试。","",
              "原生LFR允许为生成约束合并社区，因此实际size可能超出-minc/-maxc参数。root已接受其为同一固定生成参数regime的完整输入：不重选图、不改truth、不换seed。完整每图size分布保留于catalog，摘要与outlier数量在scale_statistics.csv；每条预冻结query的truth size/volume/cut及outlier标记在scale_query_statistics.csv，若异常进入query也保留。最终不得声称所有实际社区都在100…200内；log n斜率可另以log truth volume协变量作敏感性分析。","",
              "复跑入口：`.venv/bin/python experiments/data_generation/scale_generate.py`；已有完整raw记录重用，完成catalog受哈希保护。验证：scale_validate.py；纯加载计量：scale_load_benchmark.py；报告：scale_summarize.py。","",
              "如1m出现timeout/资源失败，catalog与attempt记录明确失败，算法为NOT RUN；不得把资源预测或较小图外推当成百万节点实测成功。"]
    load_path=out/"scale_load_benchmark.json"
    if load_path.exists():
        load=json.loads(load_path.read_text())["rows"]
        lines += ["","## 独立进程纯加载实测","","每图一个fresh Python进程，未扫描lazyedges、未调用算法、未做文件SHA扫描。baseline包含Python/NumPy/SciPy导入；mmap逻辑容量与进程resident memory不能混写。","",
                  "| n | 纯load秒范围 | 进程peak RSS MB范围 | mmap数组逻辑MB范围 |","|---:|---:|---:|---:|"]
        for n in cfg["n_values"]:
            selected=[r for r in load if r["n"]==n]
            if selected:
                sec=[r["load_seconds"] for r in selected];rss=[r["loaded_max_rss_bytes"]/1e6 for r in selected];logical=[r["arrays_logical_bytes"]/1e6 for r in selected]
                lines.append(f"| {n} | {min(sec):.6f}…{max(sec):.6f} | {min(rss):.3f}…{max(rss):.3f} | {min(logical):.3f}…{max(logical):.3f} |")
    review=ROOT/"reviews/data_generation/scale_REVIEW.md";review.parent.mkdir(parents=True,exist_ok=True);review.write_text("\n".join(lines)+"\n")
    summary={"completed_cases":len(rows),"expected_cases":9,"status_counts":{s:sum(r["status"]==s for r in rows) for s in ["CALIBRATED","UNREACHED","GENERATION_FAILED"]},
             "community_size_outlier_count":sum(r["community_size_outliers"] for r in rows),"query_truth_size_outlier_count":sum(r["truth_size_outlier"] for r in query_rows),
             "algorithm_status":"NOT_RUN_DATA_AND_STORAGE_ONLY","catalog_sha256":sha(ROOT/"data/scale/catalog.json"),"configuration_sha256":sha(ROOT/"experiments/data_generation/scale_config.json")}
    (out/"scale_summary.json").write_text(json.dumps(summary,indent=1));print(json.dumps(summary))
if __name__=="__main__":main()
