#!/usr/bin/env python3
"""Snapshot results with per-file SHA-256; exclude live jobs and environments."""
from pathlib import Path
import argparse,json,zipfile,hashlib,datetime
from portable_replay import validate_index
ROOT=Path(__file__).resolve().parents[1]
def file_sha256(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',default='DELIVERY.zip');p.add_argument('--phase',choices=['interim','final'],default='final');p.add_argument('--analysis',default='analysis/baseline73_v2');a=p.parse_args()
 selected=set()
 def add(path):
  if 'source_archive_history' in path.parts:return
  # The delivery contract excludes third-party paper PDFs. Local primary
  # archives remain preserved; their URL/retrieval/hash records are delivered.
  if path.suffix.lower()=='.pdf' and 'setup' in path.parts:return
  if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':selected.add(path)
 def tree(path):
  if path.exists():
   for f in path.rglob('*'):add(f)
 for folder in ['adapters','candidates','lab','tools','tests','configs','docs','context','provenance','patches','reports','analysis','verification']:
  tree(ROOT/folder)
 for filename in ['AGENTS.md','README_ZH.md','GOAL_MODE_PROMPT_ZH.md','START_HERE.sh','REPRODUCE.sh','requirements.txt','RESUME.md']:
  add(ROOT/filename)
 tree(ROOT/'work/setup');tree(ROOT/'work/dev_lfr');tree(ROOT/'work/smoke');tree(ROOT/'work/plans')
 for pattern in ['*.json','*.log']:
  for f in (ROOT/'work').glob(pattern):add(f)
 # Portable score verification also needs the exact pinned source/binary
 # files that raw records reference. Deliver these at their relative paths,
 # alongside the complete source archive, without rewriting raw metadata.
 replay_index=ROOT/'provenance/replay_index.json'
 if replay_index.exists():
  index=json.loads(replay_index.read_text())
  for relative in index['files']:
   path=(ROOT/relative).resolve()
   path.relative_to(ROOT)
   if not path.is_file():raise ValueError('Missing portable replay payload '+relative)
   add(path)
 # Include only finished attempt directories, never files a live algorithm writes.
 current_rows=json.loads((ROOT/a.analysis/'results.json').read_text()) if (ROOT/a.analysis/'results.json').exists() else []
 scored_snapshot={r['job_id'] for r in current_rows if r['status']!='NOT_RUN'}
 for runroot in (ROOT/'work').iterdir():
  if not runroot.is_dir():continue
  for record in runroot.glob('*/result.json'):
   if runroot.name=='baseline73_v2' and a.phase=='interim' and record.parent.name not in scored_snapshot:continue
   tree(record.parent)
 snapshots=[];payload_bytes=0
 out=ROOT/a.output
 closeout=None
 if a.phase=='final':
  closeout_path=ROOT/'provenance/final_closeout.json'
  if not closeout_path.exists():raise ValueError('Final delivery requires evidence-based final_closeout.json; use --phase interim for snapshots')
  closeout=json.loads(closeout_path.read_text())
  if closeout.get('status') not in ['IMPROVEMENT_CONFIRMED','DEV_SIGNAL_ONLY','NO_REPRODUCIBLE_GAIN','BLOCKED_ENV','BUDGET_EXHAUSTED']:
   raise ValueError('Missing truthful final study status')
  if closeout.get('required_artifacts_audit_pass') is not True:raise ValueError('Required final artifacts have not passed the closeout audit')
  if not replay_index.is_file():raise ValueError('Final delivery requires canonical portable replay index')
  validate_index(index,ROOT)
  sources=json.loads((ROOT/'provenance/locked_source_trees_manifest.json').read_text())
  source_archive=ROOT/'provenance/locked_source_trees.tar.gz'
  if not source_archive.is_file() or file_sha256(source_archive)!=sources['sha256']:raise ValueError('Missing or hash-mismatched locked source archive')
  if any(Path(f['path']).suffix.lower()=='.pdf' for f in sources['files']):raise ValueError('Remove third-party paper PDFs from final source archive, retaining local history and source metadata')
  for name in ['BASELINE_REPORT_ZH.md','FAILURE_MAP_ZH.md','CANDIDATE_DECISION_ZH.md','FINAL_REPORT_ZH.md']:
   if not (ROOT/'reports'/name).is_file():raise ValueError('Missing required report '+name)
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for f in sorted(selected):
   data=f.read_bytes();rel=f.relative_to(ROOT).as_posix();info=zipfile.ZipInfo.from_file(f,arcname=rel);z.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=6);payload_bytes+=len(data)
   snapshots.append({'path':rel,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
  manifest={'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'phase':a.phase,'final_goal_complete':a.phase=='final','final_status':closeout.get('status') if closeout else None,'payload_bytes':payload_bytes,'files':snapshots,'source_tree_archive':'provenance/locked_source_trees.tar.gz','excluded':['.venv and global environments','third-party research paper PDFs; their URL/retrieval/SHA256 records preserved','external git metadata and build objects; actual source trees/licenses provided in the source archive','live unfinished job artifacts','remote publication'],'study_scope':'ordinary undirected unweighted graph-only full-graph OCD; native-K/oracle-K separate; CPU serial one thread'}
  z.writestr('DELIVERY_MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
 # Verify archive against its actual bytes, not mutable live filesystem paths.
 with zipfile.ZipFile(out) as z:
  if z.testzip() is not None:raise ValueError('ZIP CRC failure')
  m=json.loads(z.read('DELIVERY_MANIFEST.json'))
  for f in m['files']:
   data=z.read(f['path'])
   if len(data)!=f['bytes'] or hashlib.sha256(data).hexdigest()!=f['sha256']:raise ValueError('Manifest mismatch '+f['path'])
  if a.phase=='final':
   embedded_index=json.loads(z.read('provenance/replay_index.json'))
   for path,expected in embedded_index['files'].items():
    data=z.read(path)
    if len(data)!=expected['size_bytes'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:raise ValueError('Embedded replay index mismatch '+path)
   embedded_sources=json.loads(z.read('provenance/locked_source_trees_manifest.json'))
   if hashlib.sha256(z.read('provenance/locked_source_trees.tar.gz')).hexdigest()!=embedded_sources['sha256']:raise ValueError('Embedded source archive mismatch')
 record={'archive':out.name,'bytes':out.stat().st_size,'sha256':file_sha256(out),'payload_files':len(snapshots),'phase':a.phase,'verified_all_zip_payload_hashes':True,'verified_embedded_replay_index_payloads':a.phase=='final','verified_embedded_source_archive_sha256':a.phase=='final'}
 out.with_suffix('.sha256.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
if __name__=='__main__':main()
