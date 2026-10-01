"""Read-only aggregation of every planned M4 main offline diagnosis.

Derived tables can be refreshed; single-query raw, cache and receipts stay
immutable. No graph, diffusion or method modules are imported.
"""
from pathlib import Path
from fractions import Fraction
from collections import Counter
import argparse
import csv
import json
import math
import statistics
import sys
import time
PROJECT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(PROJECT))
from experiments.diagnostics.storage import sha,stamp,scoped_output
from experiments.diagnostics.scope_contract import load_scope


def distribution(values):
    values=sorted(float(v) for v in values if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v))
    def quantile(p):
        position=(len(values)-1)*p;i=int(position);return values[i]+(values[min(i+1,len(values)-1)]-values[i])*(position-i)
    return {'count':len(values),'mean':statistics.fmean(values) if values else None,'median':statistics.median(values) if values else None,'min':values[0] if values else None,'q05':quantile(.05) if values else None,'q95':quantile(.95) if values else None,'max':values[-1] if values else None}


def read_rows(folder,manifest):
    rows=[];input_hashes={};issues=[];pooled={'dev':[],'test':[]}
    for q in manifest['frozen']['queries']:
        row={k:q[k] for k in ['diagnostic_query_id','task','split','case_id','seed','community_index']}
        row.update(diagnostic_status='NOT_RUN',static_exact_available=False,coverage_completed=False,finite_numeric_m_c_completed=False)
        attempts=sorted((folder/'queries'/q['diagnostic_query_id']).glob('attempt_*'));row['attempt_count']=len(attempts)
        for attempt in attempts:
            receipt=attempt/'receipt.json'
            if receipt.exists():input_hashes[str(receipt.relative_to(PROJECT))]=sha(receipt)
        if not attempts:rows.append(row);continue
        attempt=attempts[-1];row['attempt']=str(attempt.relative_to(PROJECT));receipt=attempt/'receipt.json';result=attempt/'result.json';static=attempt/'static_diagnosis.json';values=[]
        try:
            terminal=json.loads(receipt.read_text()) if receipt.exists() else {'status':'UNFINISHED'}
            if terminal.get('diagnostic_query_id',q['diagnostic_query_id'])!=q['diagnostic_query_id']:raise ValueError('Receipt query identity mismatch')
            row.update(diagnostic_status=terminal['status'],coverage_completed=terminal.get('coverage_analysis_completed') is True,finite_numeric_m_c_completed=terminal.get('completed_m_c_claim') is True,controller_wall_seconds=terminal.get('observed_wall_seconds'),peak_sum_rss_bytes=terminal.get('peak_sum_rss_bytes'),finished_support_observations=terminal.get('finished_support_observations'),partial_observed_bounds=terminal.get('partial_coverage'))
            diagnostic=None;worker=None
            if result.exists():
                digest=sha(result);input_hashes[str(result.relative_to(PROJECT))]=digest
                if terminal.get('result_sha256') and terminal['result_sha256']!=digest:raise ValueError('Result raw changed')
                worker=json.loads(result.read_text())
                if not isinstance(worker,dict) or worker.get('diagnostic_query_id')!=q['diagnostic_query_id']:raise ValueError('Result query identity/schema mismatch')
                diagnostic=worker.get('diagnosis') or worker.get('static_diagnosis')
                row.update(offline_worker_wall_seconds=worker.get('worker_wall_seconds_before_final_serialization'),offline_worker_cpu_seconds=worker.get('worker_cpu_seconds_before_final_serialization'))
            if diagnostic is None and static.exists():
                input_hashes[str(static.relative_to(PROJECT))]=sha(static);diagnostic=json.loads(static.read_text())
            if diagnostic is not None:
                row['static_exact_available']=True
                for key in ['C_subset_R','rho_hat','outside_truth_volume','outside_volume_ratio','failure_class','failure_mechanism','truth_volume','region_volume','truth_size','region_size','symmetric_difference_size','Z_output_minus_truth_exact','Z_output_minus_truth','Z_gap_per_symmetric_difference_exact','Z_gap_per_symmetric_difference','new_solver_cpu_seconds','new_solver_wall_seconds','primary_activation']:
                    row[key]=diagnostic.get(key)
                row['FP']=diagnostic.get('FP');margins=diagnostic.get('single_step_margins',[]);values=[Fraction(v['margin_exact']) for v in margins]
                row.update(single_step_margin_count=len(values),single_step_margin_negative_count=sum(v<0 for v in values),single_step_margin_min_exact=str(min(values)) if values else None,single_step_margin_min=float(min(values)) if values else None,single_step_margin_negative_fraction=sum(v<0 for v in values)/len(values) if values else None,single_step_margin_distribution=diagnostic.get('single_step_margin_distribution'))
                coverage=diagnostic.get('coverage_mass',{});row['coverage_status']=coverage.get('status')
                row['first_observed_coverage']=coverage.get('first_observed_coverage')
                row['first_recorded_grid_coverage']=coverage.get('first_recorded_grid_coverage')
                row['final_bisection_upper_coverage']=coverage.get('final_bisection_upper_coverage')
                row['bisections_completed']=len(coverage.get('bisections',[]))
                if row['finite_numeric_m_c_completed']:
                    if terminal['status']!='COMPLETED' or coverage.get('status')!='NUMERIC_COVERAGE_BRACKET' or coverage.get('relative_tolerance_met') is not True:raise ValueError('Invalid finite m_c completion claim')
                    for key in ['m_c_lower','m_c_upper','relative_bracket_width','m_c_over_3ds','m_c_over_m_act','m_c_over_m_jstar','m_c_over_m_jstar_plus1']:
                        row[key]=coverage.get(key)
            elif terminal['status']=='COMPLETED':raise ValueError('Completed diagnostic lacks exact static fields')
        except Exception as error:
            issues.append({'query':q['diagnostic_query_id'],'error':repr(error)});row.update(diagnostic_status='INTEGRITY_FAIL',coverage_completed=False,finite_numeric_m_c_completed=False,integrity_error=repr(error))
        if row['static_exact_available'] and row['diagnostic_status']!='INTEGRITY_FAIL':pooled[q['split']].extend(values)
        rows.append(row)
    return rows,input_hashes,issues,pooled


def summarize(rows,pooled):
    panels={}
    for split in ['dev','test']:
        planned=[r for r in rows if r['split']==split];static=[r for r in planned if r['static_exact_available'] and r['diagnostic_status']!='INTEGRITY_FAIL'];done=[r for r in planned if r['finite_numeric_m_c_completed'] and r['diagnostic_status']=='COMPLETED']
        fields=['rho_hat','outside_truth_volume','outside_volume_ratio','Z_output_minus_truth','Z_gap_per_symmetric_difference','single_step_margin_min','single_step_margin_negative_fraction','offline_worker_cpu_seconds','offline_worker_wall_seconds']
        ratios=['m_c_upper','m_c_over_3ds','m_c_over_m_act','m_c_over_m_jstar','m_c_over_m_jstar_plus1','relative_bracket_width']
        panels[split]={'planned_main_queries':len(planned),'status_counts':dict(Counter(r['diagnostic_status'] for r in planned)),'static_exact_available':len(static),'coverage_completed_including_no_finite':sum(r['coverage_completed'] for r in planned),'finite_numeric_m_c_completed':len(done),'no_finite_coverage':sum(r.get('coverage_status')=='NO_FINITE_COVERAGE' and r['coverage_completed'] for r in planned),'C_subset_R_true':sum(r.get('C_subset_R') is True for r in static),'C_subset_R_frequency_among_exact_available':sum(r.get('C_subset_R') is True for r in static)/len(static) if static else None,'failure_class_counts_exact_available':dict(Counter(str(r.get('failure_class')) for r in static)),'failure_mechanism_counts_exact_available':dict(Counter(str(r.get('failure_mechanism')) for r in static)),'static_available_distributions':{key:distribution([r.get(key) for r in static]) for key in fields},'completed_finite_m_c_distributions':{key:distribution([r.get(key) for r in done]) for key in ratios},'first_observed_coverage_outside_volume_completed_finite':distribution([(r.get('first_observed_coverage') or {}).get('outside_truth_volume') for r in done]),'pooled_single_step_margin_arithmetic_all_static':{'count':len(pooled[split]),'negative':sum(v<0 for v in pooled[split]),'zero':sum(v==0 for v in pooled[split]),'positive':sum(v>0 for v in pooled[split]),'distribution':distribution([float(v) for v in pooled[split]])},'scope':'All planned fixed main queries; successful and failed primary recovery both included. Partial diagnostic intervals remain in query rows. No imputation, method tuning, or outcome filter.'}
    return panels


def save_view(path,value):
    temporary=path.with_suffix(path.suffix+'.refresh');temporary.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n');temporary.replace(path)


def apply_scope(rows,pooled,admission,issues):
    result=[]
    identity=('diagnostic_query_id','task','split','case_id','seed','community_index','attempt_count')
    for row in rows:
        decision=admission[row['diagnostic_query_id']]
        row=dict(row,diagnostic_scope_allowed=decision['allowed'],diagnostic_scope_reason=decision['reason'])
        if not decision['allowed']:
            retained=row
            row={key:retained[key] for key in identity}
            row.update(diagnostic_scope_allowed=False,diagnostic_scope_reason=decision['reason'],
                       diagnostic_status='NOT_RUN_G_E2_NOT_PASS',static_exact_available=False,
                       coverage_completed=False,finite_numeric_m_c_completed=False)
            if retained['attempt_count']:
                row.update(diagnostic_status='RETAINED_OUT_OF_SCOPE',out_of_scope_retained_diagnostic_fields=retained)
                issues.append({'query':row['diagnostic_query_id'],'error':'Existing test diagnostic attempt lacks current scope authorization; evidence retained, not aggregated'})
        result.append(row)
    if any(not r['diagnostic_scope_allowed'] and r['split']=='test' for r in result):pooled['test']=[]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',default='results/diagnostics/m4_main_v12_001');args=parser.parse_args();folder=scoped_output(args.run);wall=time.perf_counter();cpu=time.process_time();manifest=json.loads((folder/'manifest.json').read_text())
    scope,admission,scope_hashes=load_scope(folder,manifest)
    rows,hashes,issues,pooled=read_rows(folder,manifest)
    rows=apply_scope(rows,pooled,admission,issues);hashes.update(scope_hashes)
    panels=summarize(rows,pooled);output=folder/'analysis';output.mkdir(exist_ok=True)
    save_view(output/'query_diagnostics.json',rows)
    fields=sorted({k for r in rows for k in r});temporary=output/'query_diagnostics.csv.refresh'
    with temporary.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for row in rows:writer.writerow({k:json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    temporary.replace(output/'query_diagnostics.csv')
    report={'schema_version':1,'generated_utc':stamp(),'status':'FAIL' if issues else 'PASS_AVAILABLE_DIAGNOSTICS','manifest_sha256':sha(folder/'manifest.json'),'frozen_sha256':manifest['frozen_sha256'],'source_sha256':{str(Path(__file__).relative_to(PROJECT)):sha(Path(__file__)),'experiments/diagnostics/storage.py':sha(PROJECT/'experiments/diagnostics/storage.py')},'input_sha256':hashes,'derived_view_sha256':{name:sha(output/name) for name in ('query_diagnostics.json','query_diagnostics.csv')},'query_count_planned':len(rows),'panels':panels,'integrity_issues':issues,'actual_command':[sys.executable,*sys.argv],'analysis_cpu_seconds_before_final_serialization':time.process_time()-cpu,'analysis_wall_seconds_before_final_serialization':time.perf_counter()-wall,'runtime_role':'offline reporting only; excluded from method/diagnosis solve timing','bootstrap':'NOT_RUN; no new statistical procedure','raw_measurements_modified':False,'derived_views_refreshable':True}
    report['diagnostic_scope']=scope
    report['source_sha256']['experiments/diagnostics/scope_contract.py']=sha(PROJECT/'experiments/diagnostics/scope_contract.py')
    save_view(output/'summary.json',report);print(json.dumps({'status':report['status'],'queries':len(rows),'diagnostic_status_counts':dict(Counter(r['diagnostic_status'] for r in rows))}))
    if issues:raise SystemExit(1)


if __name__=='__main__':main()
