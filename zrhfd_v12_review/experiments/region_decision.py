from pathlib import Path
import gzip,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.bootstrap_statistics import paired_bootstrap
from experiments.common import sha,write_new
folder=ROOT/'results/m4/dev_region_v12_002';pairs={};failures=[]
for path in sorted((folder/'raw').glob('*.json.gz')):
    with gzip.open(path,'rt') as f:row=json.load(f)
    if row['status']!='COMPLETED':failures.append(row['task']);continue
    query=(row['input']['case_id'],row['input']['query_index'])
    pairs.setdefault(query,{})['cap' if row['configuration']['region']=='R-cap' else 'supp']=row['evaluation']['F1']
expected=336;paired=[(q,p) for q,p in pairs.items() if set(p)=={'cap','supp'}]
if failures or len(paired)!=expected:raise RuntimeError(f'Region comparison incomplete: {len(paired)}/{expected}, errors{len(failures)}')
groups={}
for (case,qi),p in paired:groups.setdefault(case,[]).append(p['cap']-p['supp'])
summary=paired_bootstrap([groups[k] for k in sorted(groups)])
summary.update(contrast='R-cap(1/2) minus R-supp',primary_region='R-cap' if summary['percentile_95_CI'][0]>0 else 'R-supp',
    decision_rule='change primary only if paired mean difference 95% interval lower endpoint >0',
    test_queries_used=0,dev_catalog_sha256=sha(ROOT/'data/dev/catalog_v12.json'),
    run_manifest_sha256=sha(folder/'manifest.json'),raw_count=len(list((folder/'raw').glob('*.json.gz'))),
    all_raw_sha256={str(p.relative_to(ROOT)):sha(p) for p in (folder/'raw').glob('*.json.gz')})
dest=ROOT/'results/m4/REGION_DECISION.json'
if dest.exists():
    if json.loads(dest.read_text())!=summary:raise RuntimeError('Immutable region decision mismatch')
else:write_new(dest,summary)
print(json.dumps({k:v for k,v in summary.items() if k!='all_raw_sha256'},indent=2,ensure_ascii=False))
