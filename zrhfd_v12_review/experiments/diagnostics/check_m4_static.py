"""Code/schema-only preparation checks; no graph solve or pipeline invocation."""
from pathlib import Path
from unittest.mock import patch
from collections import Counter
import argparse
import ast
import json
import sys
import uuid
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from experiments.diagnostics.storage import write_json,sha
from experiments.diagnostics.run_m4 import plan,partial_observations,validate_diagnostic_result,read_progress,recover_abandoned
from experiments.diagnostics.m4_query import static_diagnosis,coverage_observations,POLICY


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='reviews/diagnostics/m4_static_v12_001.json');args=parser.parse_args();violations=[];parsed=[]
    for name in ['storage.py','m4_query.py','m4_worker.py','run_m4.py','check_m4_static.py']:
        path=PROJECT/'experiments/diagnostics'/name;tree=ast.parse(path.read_text());parsed.append(str(path.relative_to(PROJECT)))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and node.module=='zrhfd.pipeline':violations.append('pipeline import '+name)
    rows,manifests=plan(['results/m4/dev_main_v12_002','results/m4/test_main_v12_002']);counts=dict(Counter(r['split'] for r in rows))
    if counts!={'dev':336,'test':432}:violations.append('full main query counts')
    if POLICY['quality_filter'] is not None or not POLICY['all_completed_main_queries']:violations.append('outcome-based selection')
    class StubGraph:
        integer_weights=True
        def stats(self,C):return {'volume':3,'cut':1,'Z_exact':'2/3'}
    base={'scope':'legacy dev-only text','Z_output_exact':'1/2','Z_truth_exact':'2/3','symmetric_difference':[2],'diagnosis_seconds':0.}
    with patch('experiments.diagnostics.graph_query.diagnose_graph_query',return_value=base.copy()):
        diagnosis=static_diagnosis(StubGraph(),0,[[0,1,2]],0,{},'test')
    if diagnosis['Z_output_minus_truth_exact']!='-1/6' or diagnosis['Z_gap_per_symmetric_difference_exact']!='-1/6':violations.append('exact signed gap normalization')
    with patch('experiments.diagnostics.graph_query.diagnose_graph_query',return_value=dict(base,symmetric_difference=[])):
        zero=static_diagnosis(StubGraph(),0,[[0,1,2]],0,{},'test')
    if zero['Z_gap_per_symmetric_difference_exact'] is not None:violations.append('zero symmetric difference normalization')
    def observation(mass,role,outside):return {'mass':mass,'covered':True,'outside_truth_volume':outside,'support_volume':12+outside,'support_size':5,'role':role,'source':'controlled schema fixture','scaled_kkt_residual':0.}
    mc={'status':'NUMERIC_COVERAGE_BRACKET','m_c_upper':1.5001,'outside_truth_volume_first_covered_upper':2,'support_size_first_covered_upper':5,'bracket_trace':[observation(2.,'recorded_grid_bracket',7),observation(1.75,'coverage_bisection',4)]}
    extra=coverage_observations(mc,1.,{'m_act':1.2})
    if extra['first_observed_coverage']['mass']!=2 or extra['first_recorded_grid_coverage']['outside_truth_volume']!=7 or extra['final_bisection_upper_coverage']['mass']!=1.5001:violations.append('first vs refined coverage distinction')
    partial=partial_observations([{'event':'support_probe_finished','mass':1.,'covered':False},{'event':'support_probe_finished','mass':2.,'covered':True,'outside_truth_volume':7}])
    if partial['m_c_completion_claim'] or partial['observed_uncovered_mass_lower']!=1 or partial['observed_covered_mass_upper']!=2:violations.append('partial interval misreported as completed')
    completed={'status':'COMPLETED','diagnostic_query_id':'controlled','source_raw_sha256':'controlled','diagnosis':{'coverage_mass':{'status':'NUMERIC_COVERAGE_BRACKET','m_c_lower':1.,'m_c_upper':1.00001,'relative_bracket_width':1e-5,'relative_tolerance_met':True}},'worker_wall_seconds_before_final_serialization':.1,'worker_cpu_seconds_before_final_serialization':.05}
    validate_diagnostic_result(completed,'controlled','controlled')
    rejected=[]
    for name,value in [('non_object',[]),('wrong_id',dict(completed,diagnostic_query_id='other')),('wrong_source',dict(completed,source_raw_sha256='other')),('bad_time',dict(completed,worker_cpu_seconds_before_final_serialization=float('nan'))),('no_coverage',dict(completed,diagnosis={})),('unmet_tolerance',dict(completed,diagnosis={'coverage_mass':dict(completed['diagnosis']['coverage_mass'],relative_tolerance_met=False)}))]:
        try:validate_diagnostic_result(value,'controlled','controlled');violations.append('accepted bad terminal schema '+name)
        except (ValueError,TypeError):rejected.append(name)
    fixture=PROJECT/'results/diagnostics'/('m4_static_fixture_'+str(uuid.uuid4()));progress=fixture/'progress';progress.mkdir(parents=True)
    write_json(progress/'00000.json',{'event':'support_probe_finished','mass':2.,'covered':True,'support':[0,1,2],'support_volume':19,'outside_truth_volume':7})
    (progress/'00001.json').write_text('{"event":')
    write_json(progress/'00002.json',[])
    write_json(progress/'00003.json',{'event':'static_exact_diagnostics_finished'})
    events,malformed=read_progress(fixture)
    if len(events)!=2 or len(malformed)!=2 or partial_observations(events)['first_observed_coverage']['outside_truth_volume']!=7:violations.append('malformed progress lost valid partial observation')
    abandoned=recover_abandoned(fixture,'controlled')
    if abandoned['status']!='ABANDONED_PREVIOUS_DIAGNOSTIC' or abandoned['partial_coverage']['m_c_completion_claim'] or abandoned['partial_coverage']['observed_covered_mass_upper']!=2:violations.append('abandoned resume lost partial diagnostic')
    evidence={'schema_version':1,'status':'PASS' if not violations else 'FAIL','violations':violations,'planned_main_queries':counts,'total':len(rows),'upstream_manifest_sha256':manifests,'parsed_sources':parsed,'parsed_source_sha256':{p:sha(PROJECT/p) for p in parsed},'mocked_arithmetic_schema':{'normalized_gap':diagnosis['Z_gap_per_symmetric_difference_exact'],'zero_difference':zero['Z_gap_per_symmetric_difference_exact'],'coverage_distinction':extra,'partial_interval':partial},'terminal_schema_rejected_fixtures':rejected,'malformed_progress_fixture':{'path':str(fixture.relative_to(PROJECT)),'valid_events_retained':len(events),'malformed_events_preserved':malformed,'abandoned_receipt':abandoned},'graph_diffusion_solves_invoked':False,'pipeline_invocations':0,'actual_diagnostics_executed':False,'source_sha256':sha(Path(__file__))}
    write_json(PROJECT/args.output,evidence);print(json.dumps({'status':evidence['status'],'violations':violations,'queries':counts,'solver_invoked':False}))
    if violations:raise SystemExit(1)


if __name__=='__main__':main()
