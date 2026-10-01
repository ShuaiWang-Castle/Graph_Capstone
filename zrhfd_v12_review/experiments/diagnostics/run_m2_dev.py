"""Actual immutable diagnostics of completed M2 dev main outputs."""
from pathlib import Path
from dataclasses import asdict
import argparse
import hashlib
import itertools
import json
import sys
import time
import numpy as np
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from zrhfd.graph import Graph
from zrhfd.pipeline import Config,run
from experiments.diagnostics.graph_query import diagnose_graph_query,support_at,cache_snapshot,graph_key


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='results/diagnostics/m2_dev_v12_001');args=parser.parse_args();output=PROJECT/args.output;output.mkdir(parents=True,exist_ok=True);source=PROJECT/'results/m2/run_v12_001';started=time.perf_counter();graphs={};records={};catalog=json.loads((PROJECT/'data/dev/same12/catalog.json').read_text())['cases']
    files=sorted(source.glob('*_base_*_main.json'))+sorted(source.glob('same12_*_main.json'))
    files += [source/f'lfr_n1000_o00_m50_s11_{placement}_q{qi:02d}_main.json' for placement in ['low','high'] for qi in [3,9]]
    for path in files:
        record=json.loads(path.read_text());meta=record['input'];placement=meta.get('placement','base');key=(meta['graph_path'],placement)
        if key not in graphs:
            base=Graph.load(PROJECT/meta['graph_path']);shift=30 if placement=='low' else 0
            if placement=='base':g=base
            else:g=Graph.from_edges(base.n+30,[(u+shift,v+shift,w) for u,v,w in base.edges]+list(itertools.combinations(meta['clique_vertices'],2)))
            if record['task'].startswith('same12_'):
                index=int(record['task'].split('_')[1]);truthpath=catalog[index]['truth_path'];communities=json.loads((PROJECT/truthpath).read_text())['communities']
            else:
                truthpath=str(Path(meta['graph_path']).with_name(Path(meta['graph_path']).name.replace('.graph.json','.truth.json')));communities=json.loads((PROJECT/truthpath).read_text())['communities']
                communities=[[u+shift for u in C] for C in communities]
                if placement!='base':communities.append(meta['clique_vertices'])
            graphs[key]=(g,communities,truthpath)
        g,communities,truthpath=graphs[key];truth=set(record['truth_vertices']);target=next(i for i,C in enumerate(communities) if set(C)==truth);dest=output/(record['task']+'.json')
        if dest.exists():diagnosis=json.loads(dest.read_text())['diagnosis']
        else:
            diagnosis=diagnose_graph_query(g,record['seed'],communities,target,record['result']);payload={'source_raw':str(path.relative_to(PROJECT)),'source_raw_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'task':record['task'],'diagnosis':diagnosis};dest.write_text(json.dumps(payload,indent=2)+'\n')
        records[record['task']]=(record,diagnosis,g);print(record['task'],diagnosis['failure_class'],'mc',diagnosis['coverage_mass'].get('m_c_upper'),flush=True)
        if record['task'] in ['same12_09_main','same12_10_main'] or meta.get('query_index') in [3,9] and 's11' in record['task']:
            pack={'scope':'Immutable minimal replay querypack; supplied graph retained at exact recorded path and checksum; truth used only in offline diagnosis','source_raw':str(path.relative_to(PROJECT)),'graph_path':meta['graph_path'],'graph_sha256':meta['graph_sha256'],'placement':placement,'clique_vertices':meta.get('clique_vertices',[]),'seed':record['seed'],'configuration':record['configuration'],'truth_path':truthpath,'truth_vertices':record['truth_vertices'],'reproduce_pipeline_api':'Graph.load graph_path; apply exact documented placement shift/clique if any; run(g,seed,Config(**configuration)); call diagnose_graph_query only afterward','diagnostic_path':str(dest.relative_to(PROJECT))}
            packdir=output/'querypacks';packdir.mkdir(exist_ok=True);packpath=packdir/(record['task']+'.json')
            if not packpath.exists():packpath.write_text(json.dumps(pack,indent=2)+'\n')
    comparisons=[]
    for qi in [3,9]:
        name=f'lfr_n1000_o00_m50_s11_base_q{qi:02d}_main';base,base_diag,gbase=records[name];seed=base['seed'];masses=sorted(set(row['mass'] for row in base['result']['diffusion_trace']));mass_records=[]
        for mass in masses:
            reference,_=support_at(gbase,seed,mass,full_score=True);row={'mass':mass,'base_support':reference['support'],'comparisons':[]}
            for placement in ['low','high']:
                other,diag,gother=records[f'lfr_n1000_o00_m50_s11_{placement}_q{qi:02d}_main'];shift=30 if placement=='low' else 0;actual,_=support_at(gother,other['seed'],mass,full_score=True);mapped=sorted(u-shift for u in actual['support']);score=actual['scores'][shift:shift+gbase.n]
                row['comparisons'].append({'placement':placement,'mapped_support_equal':mapped==sorted(reference['support']),'max_base_component_score_difference':float(np.max(np.abs(score-reference['scores']))),'far_clique_support_size':len(set(actual['support'])&set(other['input']['clique_vertices']))})
            mass_records.append(row)
        differences=[]
        for placement in ['low','high']:
            other,diag,gother=records[f'lfr_n1000_o00_m50_s11_{placement}_q{qi:02d}_main'];shift=30 if placement=='low' else 0;a=base['result'];b=other['result'];S0same=set(a['S0'])==set(u-shift for u in b['S0']);Rsame=set(a['region_vertices'])==set(u-shift for u in b['region_vertices']);outputdiff=sorted(set(a['vertices'])^set(u-shift for u in b['vertices']));first={}
            if a['mm_trace'] and b['mm_trace']:
                ra,rb=a['mm_trace'][0],b['mm_trace'][0];first={'same_order':ra['order']==[u-shift for u in rb['order']],'base_lambda_exact':ra['Z_before_exact'],'other_lambda_exact':rb['Z_before_exact'],'base_proposed':ra['vertices'],'other_proposed_mapped':[u-shift for u in rb['vertices']],'base_subproblem_exact':ra['mincut_objective_exact'],'other_subproblem_exact':rb['mincut_objective_exact']}
            differences.append({'placement':placement,'M_base':gbase.total,'M_other':gother.total,'j_star_base':a['j_star'],'j_star_other':b['j_star'],'S0_equal_after_mapping':S0same,'region_equal_after_mapping':Rsame,'region_volume_base':a['region_volume'],'region_volume_other':b['region_volume'],'F1_base':base['evaluation']['F1'],'F1_other':other['evaluation']['F1'],'output_symmetric_difference':outputdiff,'first_MM':first,'empirical_attribution':'Z-sweep/jstar/region changed under global M' if not S0same or not Rsame else 'Identical initial/region; exact MM objective changes under global M','scope':'Observed development-query behavior, not a repaired claim or proof'})
        comparisons.append({'base_seed':seed,'query_index':qi,'common_mass_diffusion':mass_records,'placements':differences})
    final={'schema_version':1,'scope':'36 completed base dev main queries (24 supplied LFR +12sameSBM) plus4 targeted far-clique queries; no test tuning/no headline time','queries':len(records),'base_queries':36,'failure_counts':{label:sum(diag['failure_class']==label for rec,diag,g in records.values()) for label in [None,'H1','H2']},'far_clique_comparisons':comparisons,'diagnostic_elapsed_seconds':time.perf_counter()-started,'solver_source_SHA256':hashlib.sha256((PROJECT/'zrhfd/diffusion.py').read_bytes()).hexdigest()}
    summary=output/'summary.json';cache=output/'coverage_cache.json'
    if summary.exists() or cache.exists():raise RuntimeError('Immutable summary/cache exists')
    summary.write_text(json.dumps(final,indent=2)+'\n');cache.write_text(json.dumps({'scope':'all raw offline support/bracket recomputations; cached reuse shared by graph/seed','cache':cache_snapshot()},indent=2)+'\n');print(json.dumps({k:v for k,v in final.items() if k!='far_clique_comparisons'},indent=2))


if __name__=='__main__':main()
