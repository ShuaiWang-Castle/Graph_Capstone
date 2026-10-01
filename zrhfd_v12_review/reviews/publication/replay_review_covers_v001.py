"""Stdlib offline replay of primary cover scores; no graph algorithms/tuning."""
from pathlib import Path
from fractions import Fraction
import argparse,collections,datetime,hashlib,json,math,time,zipfile

def main():
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--publication-manifest',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    start=time.perf_counter();cpu=time.process_time();archive=Path(args.archive);errors=[];counts=collections.Counter();cache={}
    expected={'dev_main_v12_002':4032,'test_main_v12_002':5184,'dev_ablations_v12_002':1008}
    public=json.loads(Path(args.publication_manifest).read_text())
    archive_sha=hashlib.sha256(archive.read_bytes()).hexdigest()
    if public['archive']['sha256']!=archive_sha or public['archive']['bytes']!=archive.stat().st_size or public['projection_counts']!=expected:raise ValueError('External publication identity/denominator mismatch')
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('COMPACT_MANIFEST.json'))
        if manifest['projection_counts']!=expected:raise ValueError('Fixed cohort count mismatch')
        listed=[e['path'] for e in manifest['members']]
        if len(listed)!=len(set(listed)) or len(z.namelist())!=len(set(z.namelist())):raise ValueError('Duplicate member')
        verified=set(listed)
        member_index={e['path']:e for e in manifest['members']}
        if not all('cover_records/'+run+'.jsonl' in verified for run in expected):raise ValueError('Missing cover member')
        for entry in manifest['members']:
            data=z.read(entry['path'])
            if len(data)!=entry['bytes'] or hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('Member integrity failure')
        def graph(rel):
            if rel not in verified:raise ValueError('Graph is not an integrity-verified member')
            if rel not in cache:
                a=json.loads(z.read(rel));n=a['n'];adj=[set() for _ in range(n)]
                for e in a['edges']:
                    u,v=e
                    if u!=v:adj[u].add(v);adj[v].add(u)
                cache[rel]=(adj,sum(map(len,adj)))
            return cache[rel]
        seen=set()
        if 'ORIGINAL_FILE_IDENTITIES.json' not in verified:raise ValueError('Unverified original identities member')
        originals=json.loads(z.read('ORIGINAL_FILE_IDENTITIES.json'))
        identities={(r['cohort'],r['task']):r for r in originals}
        if len(identities)!=10224 or len(originals)!=10224:raise ValueError('Original identity denominator/uniqueness mismatch')
        for run,expected_count in manifest['projection_counts'].items():
            primary=archive.parent/'results/m4'/run/'manifest.json'
            binding=next(r for r in public['payload'] if r['path']==primary.relative_to(archive.parent).as_posix())
            primary_bytes=primary.read_bytes()
            if binding['bytes']!=len(primary_bytes) or binding['sha256']!=hashlib.sha256(primary_bytes).hexdigest():raise ValueError('External frozen task manifest identity mismatch')
            planned={Path(s).stem for s in json.loads(primary.read_text())['jobs']}
            if len(planned)!=expected_count:raise ValueError('Frozen task denominator mismatch')
            with z.open('cover_records/'+run+'.jsonl') as stream:
                for line in stream:
                    record=json.loads(line);a=record['record'];inp=a['input'];r=a['result']
                    key=(run,a['task'])
                    if key in seen:raise ValueError('Duplicate task')
                    seen.add(key)
                    if a['task'] not in planned or key not in identities:raise ValueError('Frozen task membership mismatch')
                    original=identities[key]
                    if any(record[k]!=original[v] for k,v in [('original_path','path'),('original_sha256','sha256'),('original_file_bytes','bytes')]):raise ValueError('Original file identity mismatch')
                    if a['status']!='COMPLETED' or not a['completion_claim']:raise ValueError('Incomplete projected record')
                    for k in ['graph_path','truth_path','queries_path']:
                        rel=inp[k]
                        if rel not in verified or member_index[rel]['sha256']!=inp[k.replace('_path','_sha256')]:raise ValueError('Frozen input member binding mismatch')
                    S=set(r['vertices']);adj,M=graph(inp['graph_path']);truth=json.loads(z.read(inp['truth_path']));C=set(truth['communities'][inp['community_index']]);hits=len(S&C)
                    precision=hits/len(S) if S else 0;recall=hits/len(C) if C else 0;f1=2*hits/(len(S)+len(C)) if len(S)+len(C) else 0
                    volume=sum(len(adj[v]) for v in S);cut=sum(len(adj[v]-S) for v in S);Z=Fraction(cut,volume)+Fraction(volume,M) if volume else None
                    phi=cut/min(volume,M-volume) if min(volume,M-volume)>0 else None
                    ev=a['evaluation'];stats=a['output_stats'];bad=[]
                    for key,val in [('precision',precision),('recall',recall),('F1',f1)]:
                        if not math.isclose(float(ev[key]),val,rel_tol=1e-12,abs_tol=1e-12):bad.append(key)
                    for key,val in [('volume',volume),('cut',cut),('size',len(S))]:
                        if stats[key]!=val:bad.append(key)
                    if (stats['Z_exact'] is None)!=(Z is None) or (Z is not None and Fraction(stats['Z_exact'])!=Z):bad.append('Z_exact')
                    if (stats['phi'] is None)!=(phi is None) or (phi is not None and not math.isclose(float(stats['phi']),phi,rel_tol=1e-12,abs_tol=1e-12)):bad.append('phi')
                    if bool(a['output_contains_seed'])!=(inp['seed'] in S):bad.append('seed_membership_metadata')
                    if bad:errors.append({'task':a['task'],'fields':bad})
                    counts[run]+=1
            if counts[run]!=expected_count:errors.append({'cohort':run,'count':counts[run],'expected':expected_count})
    out=Path(args.output)
    if out.exists():raise RuntimeError('Exclusive receipt output already exists')
    receipt={'status':'PASS_PRIMARY_COVER_REPLAY' if not errors else 'FAIL','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'archive_sha256':archive_sha,'publication_manifest_sha256':hashlib.sha256(Path(args.publication_manifest).read_bytes()).hexdigest(),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'cohort_counts':dict(counts),'unique_task_count':len(seen),'errors':errors,'wall_seconds':time.perf_counter()-start,'cpu_seconds':time.process_time()-cpu,'scope':'All10224 ordinary final covers F1/P/R/size/cut/volume/exact Z/phi/seed membership metadata and archive member identity. No baseline rerun, solver-witness audit, new truth-region diagnostics or bootstrap. M6 not replayed.'}
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    if errors:raise SystemExit(1)

if __name__=='__main__':main()
