"""Portable experiment records; evaluation is separate from algorithm inputs."""
from pathlib import Path
import datetime, hashlib, json, os, resource, threading, time, traceback
import numpy as np
import psutil

ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def write_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')

def evaluate(graph,vertices,truth,region=None):
    T,C=set(vertices),set(truth);tp=len(T&C)
    precision=tp/len(T) if T else 0.;recall=tp/len(C) if C else 0.
    out={'precision':precision,'recall':recall,'F1':2*tp/(len(T)+len(C)),
         'symmetric_difference':len(T^C),'exact_recovery':T==C,
         'truth_stats':graph.stats(C)}
    if region is not None:
        R=set(region);cover=C<=R
        out.update(truth_covered=cover,failure_class=None if T==C else ('H2' if cover else 'H1'),
           outside_volume_ratio=float(graph.degree[list(R-C)].sum()/graph.degree[list(C)].sum()))
    return out

def measured(call):
    """Outer wall and sampled RSS include descendants; timeout handled by scheduler."""
    done=threading.Event();peak=[0];process=psutil.Process()
    def sample():
        while not done.is_set():
            try:
                current=process.memory_info().rss
                for child in process.children(recursive=True):
                    try:current+=child.memory_info().rss
                    except psutil.Error:pass
                peak[0]=max(peak[0],current)
            except psutil.Error:pass
            done.wait(.025)
    thread=threading.Thread(target=sample,daemon=True);thread.start();start=time.perf_counter()
    try:result=call();status='COMPLETED';error=None
    except Exception:
        result=None;status='ERROR';error=traceback.format_exc()
    finally:done.set();thread.join()
    return {'status':status,'result':result,'error_trace':error,'outer_wall_seconds':time.perf_counter()-start,
      'peak_rss_bytes_sampled_process_and_children':peak[0],
      'self_maxrss_platform_units':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
      'finished_utc':stamp()}

def source_hashes():
    return {str(p.relative_to(ROOT)):sha(p) for folder in ('zrhfd','experiments')
        for p in sorted((ROOT/folder).rglob('*')) if p.is_file() and p.suffix in ('.py','.cpp','.jl','.yaml')}

