"""Build the CPU integer flow backend in the task-local directory."""
from pathlib import Path
import subprocess,hashlib,json,datetime
root=Path(__file__).resolve().parents[1]
out=root/'work/bin/mincut128';out.parent.mkdir(parents=True,exist_ok=True)
source=root/'zrhfd/mincut128.cpp'
cmd=['clang++','-O3','-std=c++17',str(source),'-o',str(out)]
r=subprocess.run(cmd,text=True,capture_output=True)
record={'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'command':cmd,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr,
 'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
 'binary_sha256':hashlib.sha256(out.read_bytes()).hexdigest() if r.returncode==0 else None}
(root/'provenance/mincut-build.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
if r.returncode:raise SystemExit(r.returncode)
print(record['binary_sha256'])
