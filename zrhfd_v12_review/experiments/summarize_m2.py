from pathlib import Path
import json,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.common import write_new
p=ROOT/'results/m2/run_v12_001'
rows=[json.loads(x.read_text()) for x in sorted(p.glob('*.json')) if x.name!='manifest.json']
summary={'task_count':len(rows),'status_counts':{s:sum(r['status']==s for r in rows) for s in sorted({r['status'] for r in rows})},'same12':{},'lfr':{},'remote':{},'singletons':[]}
bytask={r['task']:r for r in rows}
for variant in ['main','cap05','P2','budgetM']:
 rr=[r for r in rows if r['task'].startswith('same12_') and r['input']['variant']==variant]
 ok=[r for r in rr if r['status']=='COMPLETED'];f=[r['evaluation']['F1'] for r in ok]
 summary['same12'][variant]={'expected':12,'completed':len(ok),'exact_recovery':sum(r['evaluation']['exact_recovery'] for r in ok),'mean_F1':float(np.mean(f)) if f else None,'min_F1':min(f) if f else None,'errors':[r['task'] for r in rr if r['status']!='COMPLETED']}
for case in ['lfr_n1000_o00_m50_s11','lfr_n1000_o00_m50_s12']:
 for variant in ['main','cap05']:
  rr=[r for r in rows if r['task'].startswith(case+'_base') and r['input']['variant']==variant]
  summary['lfr'][case+'_'+variant]={'completed':len(rr),'median_F1':float(np.median([r['evaluation']['F1'] for r in rr]))}
for placement in ['low','high']:
 for variant in ['main','cap05']:
  rr=[r for r in rows if r['input'].get('placement')==placement and r['input']['variant']==variant]
  changes=[r['evaluation']['F1']-bytask[r['task'].replace('_'+placement+'_','_base_')]['evaluation']['F1'] for r in rr]
  failures=[{'task':r['task'],'F1_difference':diff,'j_star_before':bytask[r['task'].replace('_'+placement+'_','_base_')]['result']['j_star'],'j_star_after':r['result']['j_star']} for r,diff in zip(rr,changes) if diff < -.01-1e-12]
  summary['remote'][placement+'_'+variant]={'completed':len(rr),'far_clique_incorporated':sum(r['far_clique_incorporated'] for r in rr),'worst_paired_F1_difference':min(changes),'failures':failures,'gate':'PASS' if not failures and not any(r['far_clique_incorporated'] for r in rr) else 'FAIL'}
for r in rows:
 if r['result'] and len(r['result']['vertices'])==1:
  summary['singletons'].append({'task':r['task'],'status':r['result']['status'],'j_act':r['result']['j_act'],'j_star':r['result']['j_star'],'m_act':r['result']['m_act'],'stop_reason':r['result']['stop_reason'],'F1':r['evaluation']['F1']})
summary['G-E1']='PASS' if all(r['gate']=='PASS' for r in summary['remote'].values()) else 'FAIL'
summary['M2']='FAIL' if summary['G-E1']=='FAIL' else 'PASS'
summary['measurement_scope']='engineering regression; formal time main experiments separate'
dest=ROOT/'results/m2/summary_v12_001.json'
if dest.exists():
 if json.loads(dest.read_text())!=summary:raise RuntimeError('Immutable summary mismatch')
else:write_new(dest,summary)
print(json.dumps(summary,ensure_ascii=False,indent=2))
