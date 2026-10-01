"""One isolated completed-main offline diagnosis, including fixed test outputs."""
from pathlib import Path
import argparse
import gzip
import importlib.metadata
import json
import sys
import time
import traceback
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from zrhfd.graph import Graph
from experiments.diagnostics.storage import sha,stamp,write_json
from experiments.diagnostics.m4_query import complete_diagnosis,POLICY


def validate_record(job,record):
    if job['method']!='zrhfd' or not job['task'].endswith('_main') or job['setting']!='no_volume':raise ValueError('Only frozen main ZR jobs are eligible')
    if record.get('status')!='COMPLETED' or record.get('completion_claim') is not True or not isinstance(record.get('result'),dict):raise ValueError('Upstream method is not completed')
    for key in ['task','method','setting']:
        if record.get(key)!=job[key]:raise ValueError('Upstream identity mismatch: '+key)
    if record['seed']!=job['query']['seed'] or record['configuration']!=job['configuration']:raise ValueError('Upstream fixed seed/configuration mismatch')
    if record['source_sha256']!=job['source_sha256'] or record['protocol_sha256']!=job['protocol_sha256']:raise ValueError('Upstream frozen source/protocol mismatch')
    if record.get('truth_in_method_path') is not False or record.get('oracle_volume') is not None:raise ValueError('Main record violated no-volume contract')
    for key in ['graph_path','graph_sha256','truth_path','truth_sha256','queries_path','queries_sha256','community_index']:
        if record['input'][key]!=job['query'][key]:raise ValueError('Upstream immutable input mismatch: '+key)


def observed_partial(events,truth,g):
    rows=[e for e in events if e['event']=='support_probe_finished'];C=set(truth)
    covered=[];uncovered=[]
    for row in rows:
        v=dict(row,covered=C<=set(row['support']),outside_truth_volume=sum(int(round(g.degree[u])) for u in set(row['support'])-C))
        (covered if v['covered'] else uncovered).append(v)
    low=max((r['mass'] for r in uncovered),default=None);high=min((r['mass'] for r in covered),default=None)
    ordered=not(low is not None and high is not None and low>=high)
    return {'status':'INCOMPLETE_OFFLINE_COVERAGE_OBSERVATIONS','observed_uncovered_mass_lower':low,'observed_covered_mass_upper':high,'observations_ordered':ordered,'first_observed_coverage':covered[0] if covered else None,'finished_support_probes':len(rows),'m_c_completion_claim':False,'note':'observed endpoints only; no completed relative-tolerance bracket or filled m_c estimate'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--request',required=True);args=parser.parse_args();directory=Path(args.request).parent
    request=json.loads(Path(args.request).read_text());descriptor=request['query'];wall=time.perf_counter();cpu=time.process_time();events=[];g=None;job=None;static=None
    def progress(kind,**details):
        nonlocal static
        if kind=='support_probe_finished' and g is not None and job is not None:
            C=set(job['query']['truth_vertices']);support=set(details['support'])
            details.update(covered=C<=support,outside_truth_volume=sum(int(round(g.degree[u])) for u in support-C),truth_role='post-solver coverage observation only; no objective or method-parameter input')
        row={'event':kind,'elapsed_wall_seconds':time.perf_counter()-wall,'elapsed_cpu_seconds':time.process_time()-cpu,**details}
        write_json(directory/'progress'/f'{len(events):05d}.json',row);events.append(row)
        if kind=='static_exact_diagnostics_finished':
            static=details['diagnosis'];write_json(directory/'static_diagnosis.json',static)
        print(kind,'mass',details.get('mass',''),flush=True)
    try:
        if request['diagnostic_policy']!=POLICY:raise RuntimeError('Offline policy differs from prepared request')
        if sha(PROJECT/request['manifest_path'])!=request['manifest_sha256']:raise RuntimeError('Immutable diagnostic manifest changed')
        for name,digest in request['source_sha256'].items():
            if sha(PROJECT/name)!=digest:raise RuntimeError('Diagnostic source changed: '+name)
        for name,version in request['dependency_versions'].items():
            if importlib.metadata.version(name)!=version:raise RuntimeError('Diagnostic dependency changed: '+name)
        if sha(PROJECT/descriptor['job_path'])!=descriptor['job_sha256']:raise RuntimeError('Immutable ordinary job changed')
        if sha(PROJECT/descriptor['raw_path'])!=request['raw_sha256']:raise RuntimeError('Immutable completed raw changed')
        job=json.loads((PROJECT/descriptor['job_path']).read_text());record=json.loads(gzip.open(PROJECT/descriptor['raw_path'],'rt').read());validate_record(job,record)
        q=job['query'];progress('completed_input_validated',task=job['task'],split=q['split'])
        for field in ['graph','truth','queries']:
            if sha(PROJECT/q[field+'_path'])!=q[field+'_sha256']:raise RuntimeError('Frozen '+field+' input changed')
        truth=json.loads((PROJECT/q['truth_path']).read_text())['communities']
        if [set(C) for C in truth]!=[set(C) for C in q['communities']] or set(q['truth_vertices'])!=set(truth[q['community_index']]):raise ValueError('Fixed query target disagrees with pinned truth file')
        load_wall=time.perf_counter();load_cpu=time.process_time();g=Graph.load(PROJECT/q['graph_path']);input_load={'wall_seconds':time.perf_counter()-load_wall,'cpu_seconds':time.process_time()-load_cpu}
        progress('offline_topology_loaded',n=g.n,graph_path=q['graph_path'],truth_sent_to_pipeline=False)
        diagnosis=complete_diagnosis(g,int(q['seed']),truth,int(q['community_index']),record['result'],q['split'],PROJECT/request['cache_directory'],progress)
        mc=diagnosis['coverage_mass'];completed=mc['status']=='NO_FINITE_COVERAGE' or mc['status']=='NUMERIC_COVERAGE_BRACKET' and mc['relative_tolerance_met'] is True
        result={'schema_version':1,'status':'COMPLETED' if completed else 'NOT_COMPLETED','diagnostic_query_id':descriptor['diagnostic_query_id'],'task':job['task'],'split':q['split'],'source_raw':descriptor['raw_path'],'source_raw_sha256':request['raw_sha256'],'source_sha256':request['source_sha256'],'manifest_sha256':request['manifest_sha256'],'ordinary_configuration':job['configuration'],'ordinary_configuration_modified':False,'diagnosis':diagnosis,'input_load':input_load,'worker_wall_seconds_before_final_serialization':time.perf_counter()-wall,'worker_cpu_seconds_before_final_serialization':time.process_time()-cpu,'measurement_role':'independent offline diagnosis; excluded from main-method runtime/F1 selection','diagnostic_policy':POLICY,'finished_utc':stamp()}
    except Exception as error:
        exception={'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()};print(exception['traceback'],file=sys.stderr,flush=True)
        partial=observed_partial(events,job['query']['truth_vertices'],g) if g is not None and job is not None else None
        result={'schema_version':1,'status':'FAILED','diagnostic_query_id':descriptor['diagnostic_query_id'],'source_raw':descriptor['raw_path'],'source_raw_sha256':request['raw_sha256'],'exception':exception,'static_diagnosis':static,'partial_coverage':partial,'worker_wall_seconds_before_final_serialization':time.perf_counter()-wall,'worker_cpu_seconds_before_final_serialization':time.process_time()-cpu,'measurement_role':'independent offline diagnosis; no completed m_c claim','finished_utc':stamp()}
    write_json(directory/'result.json',result)


if __name__=='__main__':main()
