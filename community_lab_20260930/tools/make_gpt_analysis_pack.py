#!/usr/bin/env python3
"""Small analysis supplement; DELIVERY remains the full raw-artifact package."""
from pathlib import Path
import datetime,hashlib,json,zipfile
ROOT=Path(__file__).resolve().parents[1]
def main():
 paths=set(ROOT.glob('reports/*.md'))
 for base in ['analysis/nocd_pairdot_gate_v1','analysis/nocd_checkpoint_diagnosis','configs','patches']:
  for p in (ROOT/base).rglob('*'):
   if p.is_file() and p.suffix in ['.md','.json','.csv','.png','.patch','.diff']:paths.add(p)
 relatives=['analysis/results.csv','analysis/results.json','analysis/integrated_manifest.json','analysis/candidate_profile_summary.json','analysis/full_baseline_stage_summary.json','candidates/nocd_pairdot/adapter.py','candidates/nocd_pairdot/pairdot.py','adapters/nocd_graph_only.py','external/nocd/nocd/nn/decoder.py','provenance/licenses/nocd_LICENSE','provenance/SOURCE_LOCK.json','provenance/dependency_versions.txt','docs/EXPERIMENT_PROTOCOL_ZH.md','docs/REPRODUCIBILITY_ZH.md','verification/portable_replay_full_v1/audit.json','verification/source_restore_v2/audit.json','work/setup/candidate_final_artifact_audit/scientific_scope_review/SCIENTIFIC_SCOPE_REVIEW_ZH.md','work/setup/candidate_final_artifact_audit/scientific_scope_review/ALL_EXISTING_PAIR_REGRESSIONS.csv']
 for rel in relatives:
  p=ROOT/rel
  if not p.is_file():raise FileNotFoundError(rel)
  paths.add(p)
 paths.update(ROOT.glob('analysis/quality_cost_*.png'))
 out=ROOT/'reports/GPT_PRO_ANALYSIS_PACK.zip';manifest={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'purpose':'Compact GPT Pro analysis supplement; full raw models/logs/graphs and source restoration remain in DELIVERY.zip. No remote upload, new inference or scores.','files':[]}
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for p in sorted(paths):
   data=p.read_bytes();rel=p.relative_to(ROOT).as_posix();z.writestr(rel,data);manifest['files'].append({'path':rel,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
  z.writestr('ANALYSIS_PACK_MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
 with zipfile.ZipFile(out) as z:
  if z.testzip() is not None:raise ValueError('CRC failure')
  for f in manifest['files']:
   if hashlib.sha256(z.read(f['path'])).hexdigest()!=f['sha256']:raise ValueError('Payload mismatch '+f['path'])
 record={'archive':out.relative_to(ROOT).as_posix(),'bytes':out.stat().st_size,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'files':len(paths),'crc_and_all_payload_sha_verified':True};out.with_suffix('.sha256.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
if __name__=='__main__':main()
