#!/usr/bin/env python3
"""Stdlib-only source/initial-native-metadata audit; no measurement or scoring."""
from collections import Counter
import datetime
import hashlib
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source(path, ranges):
    p = ROOT / path
    lines = p.read_text().splitlines()
    return {'path': path, 'sha256': digest(p), 'evidence_ranges': [{'start_line': start, 'end_line': end, 'text': '\n'.join(lines[start - 1:end])} for start, end in ranges]}


sources = [source('lab/runner.py', [(7, 17), (24, 39), (48, 68), (69, 84), (85, 99), (100, 117), (118, 128)]),
           source('adapters/run.py', [(95, 110), (118, 123), (135, 142)]),
           source('adapters/nocd_graph_only.py', [(25, 28), (96, 111)]),
           source('tools/summarize.py', [(24, 42)]),
           source('docs/EXPERIMENT_PROTOCOL_ZH.md', [(44, 50)])]
rows = []
for path in sorted((ROOT / 'work/baseline73_v2').glob('*__highway_native__s73/result.json')):
    d = json.loads(path.read_text())
    if d.get('status') != 'COMPLETED':
        continue
    rows.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path),
                 **{k: d.get(k) for k in ['job_id', 'status', 'device', 'threads', 'pipeline_seconds',
                                        'monitor_elapsed_seconds', 'peak_tree_rss_bytes', 'sampled_tree_cpu_seconds',
                                        'budget_seconds', 'returncode', 'resource_measurement', 'timing_definition',
                                        'thread_environment']},
                 'recorded_runner_source_matches_audited': d.get('source_hashes', {}).get(str(ROOT / 'lab/runner.py')) == sources[0]['sha256']})
stats = {'completed_initial_native_highway_records': len(rows),
         'pipeline_seconds_range': [min(r['pipeline_seconds'] for r in rows), max(r['pipeline_seconds'] for r in rows)],
         'pipeline_seconds_median': statistics.median(r['pipeline_seconds'] for r in rows),
         'runs_under_nominal_sampling_interval_0p2s': sum(r['pipeline_seconds'] < .2 for r in rows),
         'sampled_rss_exact_245760_bytes': sum(r['peak_tree_rss_bytes'] == 245760 for r in rows),
         'sampled_rss_under_1MiB': sum(r['peak_tree_rss_bytes'] < 1024 ** 2 for r in rows),
         'sampled_rss_range_bytes': [min(r['peak_tree_rss_bytes'] for r in rows), max(r['peak_tree_rss_bytes'] for r in rows)],
         'sampled_rss_median_bytes': statistics.median(r['peak_tree_rss_bytes'] for r in rows),
         'all_recorded_runner_hashes_match': all(r['recorded_runner_source_matches_audited'] for r in rows)}
findings = [
    {'id': 'WALL_START', 'status': 'SOURCE_VERIFIED', 'source': 'lab/runner.py', 'lines': [48, 69, 79, 80], 'statement': 'start at perf_counter after plan/config/source hash checks and metadata preparation, before stdout/stderr open and Popen.'},
    {'id': 'WALL_END', 'status': 'SOURCE_VERIFIED', 'source': 'lab/runner.py', 'lines': [71, 73, 76, 114], 'statement': 'end is dedicated wait-thread observation just after direct child p.wait returns; fallback monitor elapsed only without wait observation. End includes process teardown and scheduler observation delay, not precisely last-cover-write timestamp.'},
    {'id': 'CHILD_WORK', 'status': 'SOURCE_VERIFIED', 'source': 'adapters/run.py', 'lines': [100, 103, 108, 123, 141], 'statement': 'Successful child wall includes imports/load, preprocessing/serialization, awaited native subprocess, training/selection/decode, child-side provenance hashing and cover/checkpoint writes. Parent p.wait does not independently wait arbitrary orphan grandchildren.'},
    {'id': 'OUTER_EXCLUSIONS', 'status': 'SOURCE_VERIFIED', 'source': 'lab/runner.py', 'lines': [48, 51, 66, 69, 114, 121, 122, 128], 'statement': 'Runner preflight hash checks, root harness import, post-exit graph/cover validation, prediction hash and result.json write are excluded. Adapter-internal hash operations remain included.'},
    {'id': 'OFFLINE_SCORE', 'status': 'SOURCE_VERIFIED', 'source': 'tools/summarize.py', 'lines': [25, 31, 42], 'statement': 'Offline graph/truth/pred hash validation, label loading, score and per_job provenance write have separate evaluation_seconds; excluded from inference pipeline_seconds.'},
    {'id': 'RSS_ESTIMATOR', 'status': 'SOURCE_VERIFIED', 'source': 'lab/runner.py', 'lines': [83, 87, 90, 92, 99, 117], 'statement': 'Approximately every .2s plus query/scheduling time, sum current adapter and recursively enumerated descendants RSS, take maximum observed sum. Root monitoring process excluded; reads non-simultaneous; shared pages may double count; disappeared/inaccessible processes skipped; short/lived descendants and peaks can be missed.'},
    {'id': 'SOFT_RESOURCE_GUARD', 'status': 'SOURCE_VERIFIED', 'source': 'lab/runner.py', 'lines': [94, 95, 96, 7, 17], 'statement': 'memory_mb interpreted as MiB and checked against sampled historical peak; on threshold crossing send process-group SIGTERM then possible SIGKILL. No OS RLIMIT/cgroup hard allocation cap. Exit checked before guard, so a completed fast process can finish before an overshoot is acted on.'},
    {'id': 'TIMEOUT_COST', 'status': 'SOURCE_VERIFIED', 'source': 'lab/runner.py', 'lines': [12, 17, 95, 114], 'statement': 'TIMEOUT is monitored threshold+cleanup elapsed, can exceed nominal limit and include up to three-second graceful wait; never a successful completed time. budget_seconds remains independent.'},
    {'id': 'THREAD_DECLARATION', 'status': 'SOURCE_VERIFIED_RUNTIME_UNKNOWN', 'source': 'lab/runner.py', 'lines': [52, 65], 'statement': 'threads and thread_environment record requested numerical-thread settings, not OS thread count/CPU affinity/physical-core enforcement. Torch adapter sets intra-op num_threads; BigCLAM gets -nt; native Highway metadata describes serial backend. No runtime num_threads() or thread history is recorded.'},
    {'id': 'SAMPLED_CPU_COUNTER', 'status': 'SOURCE_VERIFIED', 'source': 'lab/runner.py', 'lines': [90, 92, 117], 'statement': 'sampled_tree_cpu_seconds is maximum sampled sum of lifetime user+system CPU counters for currently visible tree, not integrated full-job CPU usage; exited children can disappear from future samples.'},
    {'id': 'SHORT_NATIVE_MEMORY_RANKING', 'status': 'UNDERRESOLVED_FOR_TRUE_PEAK_COMPARISON', 'source': 'initial_highway_native_metadata', 'statement': 'Tiny observed RSS is legitimate raw sample data, but cannot substantiate true peak RAM/unique physical memory ranking or memory winner; no sampling history/count exists to recover what phase was observed. No value is estimated or replaced.'},
    {'id': 'EXACT_PEAK_THREAD_SAMPLE_HISTORY', 'status': 'UNKNOWN', 'statement': 'Exact true peak, sampling count/timestamps, native-child coverage, OS thread count, unique physical RAM, PSS/USS and GPU memory are not available in these records.'},
]
report = {'audit_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'scope': 'Read-only source and 24 COMPLETED initial Highway native result metadata only; no C1 output/quality, truth/score, measurement, rerun or modification of root artifacts.',
          'sources': sources, 'findings': findings, 'initial_highway_native_summary': stats, 'initial_highway_native_records': rows}
(HERE / 'MEASUREMENT_SEMANTICS_EVIDENCE.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
print(json.dumps({'summary': stats, 'source_runner_sha256': sources[0]['sha256']}))
