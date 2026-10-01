"""Build a bounded public review checkpoint; never alter measured artifacts."""
from pathlib import Path
import csv,datetime,gzip,hashlib,json,os,shutil,zipfile

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reviews/publication/payload_v003'
RUNS=['dev_main_v12_002','test_main_v12_002','dev_ablations_v12_002']
COUNTS=[4032,5184,1008]
def sha(data):return hashlib.sha256(data).hexdigest()
def encoded(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def pin(path):return sha(path.read_bytes())

def main():
    if OUT.exists():raise RuntimeError('Exclusive checkpoint path already exists')
    if os.statvfs(ROOT).f_bavail*os.statvfs(ROOT).f_frsize<350_000_000:raise RuntimeError('Insufficient bounded working space')
    OUT.mkdir(parents=True)
    selected={}
    def add(rel,dest=None):
        p=ROOT/rel
        if not p.is_file():raise FileNotFoundError(rel)
        selected[dest or rel]=p
    for name in ['REPORT.md','THEORY_REQUESTS.md','EXPERIMENT_PROTOCOL_ZH.md','GPT_PRO_ANALYSIS_PROMPT_ZH.md','CHANGELOG.md','THIRD_PARTY_NOTICES.md','REPRODUCE.sh']:
        add(name)
    add('PUBLIC_REVIEW_README.md','README.md')
    for folder in ['zrhfd','tests','experiments']:
        for p in (ROOT/folder).rglob('*'):
            rel=p.relative_to(ROOT).as_posix()
            if not p.is_file() or '__pycache__' in p.parts:continue
            if any(x in rel for x in ['/reference_sources/','/snapshots/','/frozen_manifests/']):continue
            if p.suffix not in ['.py','.cpp','.jl','.yaml','.sh']:continue
            add(rel)
    selected['licenses/CCFA-Skills-MIT.txt']=ROOT.parent/'research_skills/CCFA-Skills/LICENSE'
    add('provenance/plot-helper.json')
    for rel in ['external/acquire_julia.py','external/acquire_sources.py','provenance/goal-objective.md','provenance/input-manifest.json','provenance/dependency_versions.txt','provenance/environment.json','provenance/skill-provenance.json','provenance/mincut-build.json','provenance/baselines/acquisition.json','provenance/baselines/source_findings.md','provenance/baselines/hypergraph-data.json','provenance/generators/lfr_native.json','provenance/source_snapshots/formal_ordinary_v12_002/receipt.json','experiments/reproduction/lock.json','data/dev/catalog_v12.json','data/test/calibrated_lfr/catalog.json','data/test/calibrated_lfr/GENERATION_FREEZE.json']:
        add(rel)
    for run in RUNS:
        for name in ['query_results.csv','quality_cost_summary.csv','summary.json','manifest.json']:
            p=ROOT/'results/m4'/run/name
            if p.exists():add(p.relative_to(ROOT).as_posix())
    for folder in ['reviews/m4_analysis/paired_ablations_v001','reviews/m4_analysis/actual_test_v001','reviews/m4_analysis/actual_dev_v001','reviews/final_actual_review','reviews/m6_analysis','results/m6_analysis/preliminary_h3_examples','results/m1_independent','results/diagnostics/m2_dev_v12_001','results/diagnostics/m4_main_v12_001/analysis']:
        for p in (ROOT/folder).glob('*'):
            if p.is_file() and p.suffix in ['.md','.json','.csv','.py'] and p.stat().st_size<2_000_000:add(p.relative_to(ROOT).as_posix())
    for rel in ['results/m0_reference/summary.json','results/m0_reference/per_instance.csv','results/m0_reference/input_availability_audit.json','results/m0_reference/raw_measurements.sha256.json','results/m2/summary_v12_001.json','results/m6_prepared/manifest.json','results/m6_prepared/summary.json','results/m6_prepared/query_summary.csv','results/diagnostics/m4_main_v12_001/SCOPE_RECEIPT.json','reviews/m4_analysis/audit_actual_ordinary_v001.py','reviews/m4_analysis/audit_paired_ablations_v001.py','reviews/m4_analysis/verify_test_gate_from_audit_v001.py','reviews/publication/assigned_source_scope_v001.md','reviews/publication/assigned_evidence_review.md','reviews/publication/build_review_checkpoint_v001.py','reviews/publication/replay_review_covers_v001.py']:
        add(rel)
    for folder in ['figures/m4/dev_main_v12_002','figures/m4/test_main_v12_002','figures/m6/prepared_v001']:
        for p in (ROOT/folder).glob('*'):
            if p.is_file() and p.suffix in ['.png','.svg','.csv','.json','.md']:add(p.relative_to(ROOT).as_posix())
    # The copied CCFA MIT helper is shipped with its original license and pin.
    for rel in selected:
        if rel.endswith(('.py','.jl','.cpp')) and b'ccfa_plot_recipes' in selected[rel].read_bytes():
            if 'experiments/plot_helpers/ccfa_plot_recipes.py' not in selected or 'licenses/CCFA-Skills-MIT.txt' not in selected:raise RuntimeError('Missing helper license: '+rel)
    pins=json.loads((ROOT/'provenance/source_snapshots/formal_ordinary_v12_002/receipt.json').read_text())['source_sha256']
    for rel,digest in pins.items():
        if rel not in selected or pin(selected[rel])!=digest:raise RuntimeError('Frozen source27 not preserved: '+rel)
    for rel,p in sorted(selected.items()):
        q=OUT/rel;q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
    archive=OUT/'COMPACT_EVIDENCE.zip'
    members=[];cuts=[];originals=[];projection_counts={};graphs={}
    def member(z,name,data):
        z.writestr(name,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=6)
        members.append({'path':name,'bytes':len(data),'sha256':sha(data)})
        if archive.stat().st_size>80_000_000:raise RuntimeError('Bounded compact archive exceeded80MB')
    essential={'vertices','S0','region_vertices','touched_vertices','hull_best','order','sweep_vertices'}
    def reduce(value,path,removed):
        if isinstance(value,dict):
            out={}
            for k,v in value.items():
                field=path+'/'+k
                if k in ['oracle_trace','hull_vertices','stdout','stdout_preview','stdout_excerpt','dual_heights','scores','x','heights','score_vector','height_vector']:
                    b=encoded(v);removed.append({'field':field,'serialized_sha256':sha(b),'serialized_bytes':len(b),'items':len(v) if isinstance(v,(dict,list,str)) else None});continue
                out[k]=reduce(v,field,removed)
            return out
        if isinstance(value,list):return [reduce(v,path+'/'+str(i),removed) for i,v in enumerate(value)]
        return value
    def compact(a,removed):
        out={k:v for k,v in a.items() if k!='result'};result=a['result'];small={}
        def omit(field,value):
            b=encoded(value);removed.append({'field':field,'serialized_sha256':sha(b),'serialized_bytes':len(b),'items':len(value) if isinstance(value,(dict,list,str)) else None})
        lists={'vertices','S0','region_vertices','hull_best','mass_sequence'}
        for key,value in result.items():
            path='/result/'+key
            if key in lists or not isinstance(value,(dict,list)):small[key]=value
            elif key in ['config','stats']:small[key]=value
            elif key=='certificate':small[key]=reduce(value,path,removed)
            elif key in ['diffusion_trace','mm_trace']:
                rows=[]
                for i,item in enumerate(value):
                    row={}
                    for k,v in item.items():
                        if not isinstance(v,(dict,list)) or k=='vertices':row[k]=v
                        else:omit(path+'/'+str(i)+'/'+k,v)
                    rows.append(row)
                small[key]=rows
            elif key=='metadata':
                row={}
                for k,v in value.items():
                    if not isinstance(v,(dict,list)) and (not isinstance(v,str) or len(v)<2048):row[k]=v
                    else:omit(path+'/'+k,v)
                small[key]=row
            else:omit(path,value)
        out['result']=small;return out
    with zipfile.ZipFile(archive,'x',allowZip64=True,compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for run,count in zip(RUNS,COUNTS):
            rows=list(csv.DictReader((ROOT/'results/m4'/run/'query_results.csv').open()))
            if len(rows)!=count or any(r['status']!='COMPLETED' for r in rows):raise RuntimeError('Full cohort expected')
            name='cover_records/'+run+'.jsonl'
            h=hashlib.sha256();nbytes=0
            with z.open(name,'w',force_zip64=True) as stream:
                for row in rows:
                    p=ROOT/row['raw_path'];blob=p.read_bytes();a=json.loads(gzip.decompress(blob) if p.suffix=='.gz' else blob)
                    removed=[];projection=compact(a,removed)
                    record={'schema':'compact-public-review-projection-v1','original_path':row['raw_path'],'original_file_bytes':len(blob),'original_sha256':sha(blob),'removed_fields':removed,'record':projection}
                    data=encoded(record);stream.write(data);h.update(data);nbytes+=len(data)
                    if archive.stat().st_size>80_000_000:raise RuntimeError('Archive size budget while streaming')
                    originals.append({'task':a['task'],'cohort':run,'path':row['raw_path'],'bytes':len(blob),'sha256':sha(blob)})
                    inp=a['input']
                    for key in ['graph_path','truth_path','queries_path']:
                        rel=inp[key];expected=inp[key.replace('_path','_sha256')]
                        if rel in graphs and graphs[rel]!=expected:raise RuntimeError('Input hash changed')
                        graphs[rel]=expected
                projection_counts[run]=len(rows)
            members.append({'path':name,'bytes':nbytes,'sha256':h.hexdigest()})
            if archive.stat().st_size>80_000_000:raise RuntimeError('Archive size budget')
        for rel,digest in sorted(graphs.items()):
            data=(ROOT/rel).read_bytes()
            if sha(data)!=digest:raise RuntimeError('Frozen input changed: '+rel)
            member(z,rel,data)
        for rel in ['reviews/m4_analysis/actual_dev_v001/receipt.json','reviews/m4_analysis/actual_test_v001/receipt.json','reviews/m4_analysis/paired_ablations_v001/receipt.json']:
            member(z,rel,(ROOT/rel).read_bytes())
        member(z,'ORIGINAL_FILE_IDENTITIES.json',encoded(originals))
        zipmanifest={'schema':'public-compact-review-members-v1','members':members.copy(),'projection_counts':projection_counts,'input_files':len(graphs),'original_files':len(originals),'scope':'All10224 final ordinary covers and recorded metadata; listed intermediate fields omitted with serialization hashes. No algorithm execution or new mechanism diagnostics. Not complete raw-tree or M6 witness release.'}
        member(z,'COMPACT_MANIFEST.json',encoded(zipmanifest))
    with zipfile.ZipFile(archive) as z:
        for entry in members:
            h=hashlib.sha256();n=0
            with z.open(entry['path']) as stream:
                for block in iter(lambda:stream.read(1<<20),b''):h.update(block);n+=len(block)
            if h.hexdigest()!=entry['sha256'] or n!=entry['bytes']:raise RuntimeError('ZIP roundtrip failed')
    manifest={'schema':'zrhfd-public-review-publication-v1','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'goal_status':'ACTIVE','scientific_status':'DEV_GAIN_NOT_CONFIRMED_ON_TEST','G_E2':'FAIL','measured_artifacts_modified':False,'projection_counts':projection_counts,'archive_members_verified':len(members),'archive':{'path':'COMPACT_EVIDENCE.zip','bytes':archive.stat().st_size,'sha256':pin(archive)},'source27_exactly_preserved':True,'excluded':['third-party unlicensed HFD/pnorm source and binaries','platform/runtime files and credentials','third-party papers','full M6 graphs/vectors/checkpoints','complete historical raw trees','explicitly listed projection intermediate fields'],'payload':[]}
    for p in sorted(OUT.rglob('*')):
        if p.is_file():manifest['payload'].append({'path':p.relative_to(OUT).as_posix(),'bytes':p.stat().st_size,'sha256':pin(p),'git_blob_sha':hashlib.sha1(('blob '+str(p.stat().st_size)+'\0').encode()+p.read_bytes()).hexdigest()})
    (OUT/'PUBLICATION_MANIFEST.json').write_bytes(encoded(manifest))
    print(json.dumps({'status':'CHECKPOINT_BUILT_MEMBERS_VERIFIED','payload_files':len(manifest['payload'])+1,'archive_bytes':archive.stat().st_size,'archive_sha256':manifest['archive']['sha256'],'projection_counts':projection_counts,'free_bytes':os.statvfs(ROOT).f_bavail*os.statvfs(ROOT).f_frsize}),flush=True)

if __name__=='__main__':main()
