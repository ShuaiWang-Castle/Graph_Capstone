"""Rebuild tables from immutable planned jobs and raw measurements, without tuning."""
from pathlib import Path
import argparse, csv, gzip, json, math, sys
from collections import Counter, defaultdict
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.common import sha,stamp

PHI_EDGES=(.05,.15,.25,.35,.45,.55,.65)
def phi_bin(value):
    if value is None:return None
    for index,(left,right) in enumerate(zip(PHI_EDGES,PHI_EDGES[1:])):
        if left<=value<right:return str((index+1)/10)
    return None

def completed(row):return row['status']=='COMPLETED' and row['completion_claim']

def bootstrap(rows,field,replicates=10000,seed=20261005):
    groups=defaultdict(list)
    for row in rows:
        value=row.get(field)
        if value is not None and math.isfinite(value):groups[row['case_id']].append(value)
    if not groups:return None
    arrays=[np.array(groups[k],dtype=float) for k in sorted(groups)]
    all_values=np.concatenate(arrays);rng=np.random.default_rng(seed);G=len(arrays);width=max(map(len,arrays))
    chosen=rng.integers(G,size=(replicates,G));samples=np.full((replicates,G*width),np.nan)
    for position in range(G):
        for gi,a in enumerate(arrays):
            indices=np.flatnonzero(chosen[:,position]==gi)
            if not len(indices):continue
            draws=a[rng.integers(len(a),size=(len(indices),len(a)))]
            samples[indices[:,None],position*width+np.arange(len(a))[None,:]]=draws
    means=np.nanmean(samples,axis=1);medians=np.nanmedian(samples,axis=1)
    return {'queries':len(all_values),'graphs':len(arrays),'mean':float(all_values.mean()),
            'median':float(np.median(all_values)),'mean_percentile_95_CI':np.quantile(means,[.025,.975]).tolist(),
            'median_percentile_95_CI':np.quantile(medians,[.025,.975]).tolist(),
            'replicates':replicates,'seed':seed,'resampling':'graph then its queries, conditional on frozen regimes'}

def read_run(folder):
    manifest=json.loads((folder/'manifest.json').read_text());rows=[];raw_hashes={}
    # Offline input stratification also covers errors and unrun jobs; it never
    # imputes algorithm quality or changes any method rule.
    from zrhfd.graph import Graph
    truth_cache={};last_graph=[None,None]
    for jobpath in manifest['jobs']:
        job=json.loads((ROOT/jobpath).read_text());entry=job['query'];path=ROOT/job['result_path'];r={}
        if last_graph[0]!=entry['graph_path']:
            last_graph[:]=[entry['graph_path'],Graph.load(ROOT/entry['graph_path'])]
        failure=path.with_suffix('.failure.json')
        if path.exists():
            with gzip.open(path,'rt') as f:r=json.load(f)
            raw_hashes[str(path.relative_to(ROOT))]=sha(path)
        if failure.exists():
            control=json.loads(failure.read_text());status=control['status']
            raw_hashes[str(failure.relative_to(ROOT))]=sha(failure)
        else:control={};status=r.get('status','NOT_RUN')
        a=r.get('result') or {};ev=r.get('evaluation') or {};stats=r.get('output_stats') or a.get('stats') or {}
        truth=ev.get('truth_stats') or {}
        if not truth:
            key=(entry['case_id'],entry['community_index'])
            if key not in truth_cache:
                truth_cache[key]=last_graph[1].stats(entry['truth_vertices'])
            truth=truth_cache[key]
        cert=a.get('certificate') or {};meta=a.get('metadata') or {};workspaces=a.get('exact_cut_workspace',[])
        diffusion=a.get('diffusion_trace',[]);mm=a.get('mm_trace',[])
        row={'task':job['task'],'case_id':entry['case_id'],'query_index':entry['query_index'],
             'n':last_graph[1].n,
             'seed':entry['seed'],'method':job['method'],'setting':job['setting'],
             'variant':job['configuration'].get('variant',('R-cap-'+str(job['configuration'].get('theta',.5)) if job['configuration'].get('region')=='R-cap' else 'main') if job['method'] in ('zrhfd','zrhfd_ablation') else None),
             'status':status,'completion_claim':bool(r.get('completion_claim',False)) and status=='COMPLETED',
             'F1':ev.get('F1'),'precision':ev.get('precision'),'recall':ev.get('recall'),
             'Z_out':stats.get('Z'),'Z_out_exact':stats.get('Z_exact'),'phi_out':stats.get('phi'),
             'volume_out':stats.get('volume'),'size_out':stats.get('size'),'components':r.get('components'),
             'Z_truth':truth.get('Z'),'truth_phi':truth.get('phi'),'truth_volume':truth.get('volume'),
             'truth_covered':ev.get('truth_covered'),'failure_class':ev.get('failure_class'),
             'rho_hat':ev.get('rho_hat'),'outside_volume_ratio':ev.get('outside_volume_ratio'),
             'symmetric_difference':ev.get('symmetric_difference'),'exact_recovery':ev.get('exact_recovery'),
             'outer_wall_seconds':r.get('outer_wall_seconds') if status=='COMPLETED' else None,
             'observed_not_completion_seconds':control.get('wall_seconds_observed_not_completion',r.get('outer_wall_seconds')),
             'input_load_seconds':r.get('input_load_seconds'),'method_seconds':a.get('runtime_seconds') if status=='COMPLETED' else None,
             'observed_method_seconds_not_completion':a.get('runtime_seconds'),
             'native_kernel_seconds':meta.get('kernel_seconds_total'),
             'peak_rss_bytes':r.get('peak_rss_bytes_sampled_process_and_children',control.get('peak_rss_bytes')),
             'touched_volume':r.get('touched_volume',a.get('touched_volume')),
             'touched_definition':meta.get('touched_definition','diffusion support union region' if job['method']=='zrhfd' else None),
             'j_act':a.get('j_act'),'j_star':a.get('j_star'),'m_act':a.get('m_act'),
             'region_volume':a.get('region_volume'),'LB_R':cert.get('LB_R'),'gap':cert.get('gap'),
             'certificate_status':cert.get('certificate_status',cert.get('status')),'hull_best_F1':r.get('hull_best_evaluation',{}).get('F1'),
             'gap_bound':cert.get('gap_bound_telemetry',cert.get('gap_bound')),'gap_bound_exact':cert.get('gap_bound_exact'),
             'diffusion_seconds':sum(t.get('runtime_seconds',0) for t in diffusion),
             'mm_seconds':sum(t.get('telemetry',{}).get('runtime_seconds',0) for t in mm),
             'certificate_cut_execution_and_validation_seconds':sum(t.get('telemetry',{}).get('runtime_seconds',0) for t in cert.get('oracle_trace',[])),
             'exact_cut_workspace_preparation_seconds':sum(w['preparation_seconds'] for w in workspaces),
             'exact_cut_capacity_assembly_seconds':sum(w['assembly_seconds'] for w in workspaces),
             'exact_cut_native_subprocess_seconds':sum(w['native_subprocess_seconds'] for w in workspaces),
             'exact_cut_return_validation_seconds':sum(w['objective_validation_seconds'] for w in workspaces),
             'exact_cut_calls':sum(w['calls'] for w in workspaces),
             'implementation_exact_cut_backend':job.get('implementation_exact_cut_backend','original_exact'),
             'mass_count':len(a.get('mass_sequence',meta.get('mass_grid',[]))),
             'mm_steps':len(mm),'raw_path':str(path.relative_to(ROOT)) if path.exists() else None,
             'error_path':str(failure.relative_to(ROOT)) if failure.exists() else None,
             'protocol_sha256':job['protocol_sha256']}
        if row['touched_volume'] is not None and row['volume_out']:
            row['touched_over_output_volume']=row['touched_volume']/row['volume_out']
        else:row['touched_over_output_volume']=None
        rows.append(row)
    return manifest,rows,raw_hashes

def group_name(row):
    if row['method']=='zrhfd_ablation':return row['variant']
    if row['method']=='zrhfd' and row['variant']!='main':return 'zrhfd_'+row['variant']
    return row['method']+'_'+row['setting']

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run',required=True);ap.add_argument('--replicates',type=int,default=10000)
    ap.add_argument('--reference-binding',help='Explicit verified fresh reproduction binding; never replaces the original frozen panel')
    args=ap.parse_args()
    folder=ROOT/args.run;manifest,rows,hashes=read_run(folder);groups=defaultdict(list)
    reproduced_binding=None
    if args.reference_binding:
        from experiments.reproduction.cohort_binding import verify_m4_reference_binding
        reproduced_binding=verify_m4_reference_binding(ROOT/args.reference_binding,run_path=folder,verify_files=True)
        if reproduced_binding.get('status')!='PASS' or reproduced_binding.get('cohort_origin')!='FRESH_REPRODUCTION':
            raise RuntimeError('The fresh cohort reference binding did not pass')
    lookup={(r['case_id'],r['query_index'],r['method'],r['setting']):r for r in rows}
    for r in rows:
        leiden=lookup.get((r['case_id'],r['query_index'],'leiden','global'))
        r['F1_difference_from_Leiden']=(r['F1']-leiden['F1'] if completed(r) and leiden and completed(leiden) else None)
        groups[group_name(r)].append(r)
    with (folder/'query_results.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    panels={};summaries=[]
    for label,planned in sorted(groups.items()):
        done=[r for r in planned if completed(r)]
        panel={'planned':len(planned),'statuses':dict(Counter(r['status'] for r in planned)),'completed_only':{},'by_measured_truth_phi':{}}
        for field in ['F1','precision','recall','outer_wall_seconds','touched_over_output_volume','gap','F1_difference_from_Leiden']:
            panel['completed_only'][field]=bootstrap(done,field,args.replicates)
        for center in [.1,.2,.3,.4,.5,.6]:
            selected=[r for r in done if phi_bin(r['truth_phi'])==str(center)]
            planned_stratum=[r for r in planned if phi_bin(r['truth_phi'])==str(center)]
            panel['by_measured_truth_phi'][str(center)]={'planned':len(planned_stratum),
                'statuses':dict(Counter(r['status'] for r in planned_stratum)),
                'completed_F1':bootstrap(selected,'F1',args.replicates)}
        panel['truth_phi_outside_displayed_bins_queries']=sum(phi_bin(r['truth_phi']) is None for r in planned)
        panels[label]=panel
        f1=panel['completed_only']['F1'];time=panel['completed_only']['outer_wall_seconds']
        summaries.append({'method_setting':label,'planned':len(planned),'completed':len(done),
                          'F1_mean':f1['mean'] if f1 else None,'F1_median':f1['median'] if f1 else None,
                          'F1_mean_95_CI':json.dumps(f1['mean_percentile_95_CI']) if f1 else None,
                          'F1_median_95_CI':json.dumps(f1['median_percentile_95_CI']) if f1 else None,
                          'wall_mean_completed_only':time['mean'] if time else None,'wall_median_completed_only':time['median'] if time else None,
                          'status_counts':json.dumps(panel['statuses'])})
    gate={'status':'NOT RUN','reason':'Only the frozen test panel can evaluate G-E2.'}
    original_test=manifest['catalog_sha256']=='c7e97bfbb7bea8fa7708b3e9061309f170cd345ac40116f67b4a97891a7481d4'
    reproduced_test=reproduced_binding is not None and reproduced_binding.get('stage')=='M4_TEST_MAIN'
    if manifest['phase']=='main' and (original_test or reproduced_test):
        mainrows=groups.get('zrhfd_no_volume',[]);pairs=[]
        for a in mainrows:
            h=lookup.get((a['case_id'],a['query_index'],'hfd','no_volume'));l=lookup.get((a['case_id'],a['query_index'],'leiden','global'))
            if completed(a) and h and l and completed(h) and completed(l):pairs.append((a,h,l))
        low=[p for p in pairs if p[0]['truth_phi']<=.5];high=[p for p in pairs if .4<=p[0]['truth_phi']<=.5]
        allhigh=[p for p in pairs if p[0]['truth_phi']>=.4]
        def med(xs,i):return float(np.median([p[i]['F1'] for p in xs])) if xs else None
        unique_main_keys={(r['case_id'],r['query_index']) for r in mainrows}
        complete=len(pairs)==len(mainrows)==len(unique_main_keys)==432
        first=bool(low) and med(low,0)>=med(low,2)-.03
        second=bool(high) and med(high,0)>=med(high,1)+.10
        gate={'status':('PASS' if first and second else 'FAIL') if complete else 'NOT RUN',
              'complete_test_query_triples':len(pairs),'required':432,'truth_phi_le_point5_queries':len(low),
              'truth_phi_point4_to_point5_queries':len(high),'main_median_low':med(low,0),'leiden_median_low':med(low,2),
              'main_median_high':med(high,0),'hfd_no_volume_median_high':med(high,1),'Leiden_margin_condition':first,'HFD_gain_condition':second,
              'scope':'Second condition nested within G-E2 specified truth_phi<=.5 target range; raw phi retained, no nominal-mu substitution',
              'all_truth_phi_ge_point4_descriptive':{'queries':len(allhigh),'main_median':med(allhigh,0),'HFD_median':med(allhigh,1)},
              'missing_policy':'incomplete panels never pass, no imputed quality'}
        gate['cohort_origin']='FRESH_REPRODUCTION' if reproduced_binding is not None else 'ORIGINAL_FROZEN_COHORT'
        gate['reference_binding_sha256']=sha(ROOT/args.reference_binding) if reproduced_binding is not None else None
    output={'generated_utc':stamp(),'run_manifest_sha256':sha(folder/'manifest.json'),'raw_sha256':hashes,
            'panels':panels,'G_E2':gate,'statistics_scope':'Completed budget executions only, not convergence evidence. All planned failures remain in query_results.csv.',
            'touched_scope':'Each method has its own declared touched definition; main support-union telemetry is not total sparse/dense I/O.',
            'cohort_origin':'FRESH_REPRODUCTION' if reproduced_binding is not None else 'ORIGINAL_FROZEN_COHORT',
            'reference_binding':reproduced_binding,
            'test_tuning':False}
    with (folder/'quality_cost_summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
    output['derived_view_sha256']={name:sha(folder/name) for name in ('query_results.csv','quality_cost_summary.csv')}
    (folder/'summary.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'planned':len(rows),'status':dict(Counter(r['status'] for r in rows)),'G_E2':gate},ensure_ascii=False))

if __name__=='__main__':main()
