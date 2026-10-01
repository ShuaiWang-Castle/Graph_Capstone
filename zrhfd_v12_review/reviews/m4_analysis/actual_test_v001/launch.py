from pathlib import Path
import datetime, hashlib, json, os, subprocess, time
import psutil

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def utc(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def save(name, value):
    with (HERE/name).open('x') as f:
        json.dump(value, f, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())

barrier = json.loads((ROOT/'results/orchestration/m4_ordinary_analysis_barrier_v001.json').read_text())
owner = psutil.Process(barrier['owner']['pid'])
assert owner.create_time() == barrier['owner']['create_time'] and owner.status() == psutil.STATUS_STOPPED
try:
    child = psutil.Process(barrier['measured_child']['pid'])
    assert child.create_time() != barrier['measured_child']['create_time'] or child.status() in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD)
except psutil.NoSuchProcess: pass
command = [str(ROOT/'.venv/bin/python'), 'reviews/m4_analysis/audit_actual_ordinary_v001.py', '--run', 'results/m4/test_main_v12_002', '--output', 'reviews/m4_analysis/actual_test_v001/receipt.json']
pins = {p: sha(ROOT/p) for p in ['reviews/m4_analysis/audit_actual_ordinary_v001.py','results/m4/test_main_v12_002/manifest.json','results/m4/test_main_v12_002/summary.json','experiments/reproduction/lock.json']}
env = dict(os.environ)
threads = {k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMBA_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS']}
env.update(threads); env['PYTHONDONTWRITEBYTECODE']='1'
save('request.json', {'started_utc':utc(),'actual_argv':command,'cwd':str(ROOT),'thread_environment':threads,'source_sha256':pins,'launcher_sha256':sha(__file__),'scientific_measurement':False})
began=time.perf_counter(); peak=0
with (HERE/'stdout.log').open('x') as out, (HERE/'stderr.log').open('x') as err:
    proc=subprocess.Popen(command,cwd=ROOT,env=env,stdout=out,stderr=err)
    save('process_started.json', {'pid':proc.pid,'create_time':psutil.Process(proc.pid).create_time(),'started_utc':utc()})
    while proc.poll() is None:
        try:
            parent=psutil.Process(proc.pid); rss=parent.memory_info().rss
            for p in parent.children(recursive=True):
                try: rss+=p.memory_info().rss
                except psutil.Error: pass
            peak=max(peak,rss)
        except psutil.Error: pass
        time.sleep(.05)
    code=proc.returncode
receipt={'status':'PASS' if code==0 else 'FAILED','returncode':code,'finished_utc':utc(),'outer_wall_seconds':time.perf_counter()-began,'peak_sampled_process_tree_rss_bytes':peak,'source_sha256_unchanged':all(sha(ROOT/p)==s for p,s in pins.items()),'original_raw_modified':False,'measurement_completion_claim':False}
save('terminal.json',receipt);print(json.dumps(receipt));raise SystemExit(code)
