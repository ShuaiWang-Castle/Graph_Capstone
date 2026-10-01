"""Join all planned main queries to offline diagnoses without outcome filtering."""
from pathlib import Path
from collections import Counter,defaultdict
from fractions import Fraction
import argparse,csv,hashlib,json,math,statistics

ROOT=Path(__file__).resolve().parents[2]

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
    return h.hexdigest()

def read(path):return json.loads(Path(path).read_text())

def validate_query_rows(queries,diagnoses):
    planned={q['diagnostic_query_id']:q for q in queries}
    lookup={r['diagnostic_query_id']:r for r in diagnoses}
    if len(planned)!=len(queries) or len(lookup)!=len(diagnoses) or set(planned)!=set(lookup):
        raise RuntimeError('Duplicate, missing, or unplanned diagnostic query identity')
    if len(queries)!=768 or Counter(q['split'] for q in queries)!=Counter({'dev':336,'test':432}):
        raise RuntimeError('The join requires all 768 planned queries, including missing outcomes')
    if len({(q['upstream_run'],q['task']) for q in queries})!=len(queries):
        raise RuntimeError('Duplicate upstream main query in diagnosis plan')
    for key,q in planned.items():
        row=lookup[key]
        if any(row.get(field)!=q[field] for field in ('task','split','case_id','seed','community_index')):
            raise RuntimeError('Diagnostic row identity differs from its frozen query')
    return lookup

def validate_primary_identity(primary,q,job):
    # Split is supplied by the frozen job query, not by the primary CSV schema.
    if primary['case_id']!=q['case_id'] or int(primary['seed'])!=q['seed']:
        raise RuntimeError('Primary CSV query identity differs from the diagnosis plan')
    if any(job['query'].get(field)!=q[field] for field in ('split','case_id','seed','community_index')):
        raise RuntimeError('Frozen primary job query identity differs from the diagnosis plan')
    if job['task']!=q['task'] or job['method']!='zrhfd' or job['setting']!='no_volume' or job['result_path']!=q['raw_path']:
        raise RuntimeError('Diagnosis job is not this primary main-method query')
    if primary['protocol_sha256']!=q['primary_protocol_sha256'] or job['protocol_sha256']!=q['primary_protocol_sha256']:
        raise RuntimeError('Primary protocol differs from the offline diagnostic plan')

def classify(primary,diagnostic):
    if diagnostic.get('diagnostic_scope_allowed') is False:return 'DIAGNOSTIC_SCOPE_NOT_AUTHORIZED'
    done=primary['status']=='COMPLETED' and primary['completion_claim']=='True'
    if not done:return 'PRIMARY_NOT_COMPLETED'
    if primary['j_act']=='':return 'UNACTIVATED'
    if diagnostic.get('static_exact_available') and diagnostic['diagnostic_status']!='INTEGRITY_FAIL':
        if diagnostic.get('failure_class') in ('H1','H2'):return diagnostic['failure_class']
        if diagnostic.get('symmetric_difference_size')==0:return 'RECOVERED'
    if primary['exact_recovery']=='True':return 'RECOVERED'
    return primary['failure_class'] if primary['failure_class'] in ('H1','H2') else 'DIAGNOSIS_UNAVAILABLE'

def quality_bin(value):
    if value is None:return 'NOT_COMPLETED'
    if value==1:return '1.0'
    if value<.5:return '[0,.5)'
    if value<.9:return '[.5,.9)'
    return '[.9,1)'

def summarize(rows):
    panels={}
    for split in ('dev','test'):
        planned=[r for r in rows if r['split']==split]
        byclass={}
        for label in sorted({r['recovery_class'] for r in planned}):
            selected=[r for r in planned if r['recovery_class']==label];f1=[r['F1'] for r in selected if r['F1'] is not None]
            byclass[label]={'planned_queries':len(selected),'completed_quality_queries':len(f1),
                            'F1_mean':statistics.fmean(f1) if f1 else None,'F1_median':statistics.median(f1) if f1 else None,
                            'quality_bins':dict(Counter(quality_bin(r['F1']) for r in selected)),
                            'offline_diagnostic_status_counts':dict(Counter(r['diagnostic_status'] for r in selected)),
                            'objective_comparison_counts':dict(Counter(r['H2_objective_comparison'] for r in selected if r['H2_objective_comparison']))}
        panels[split]={'planned':len(planned),'primary_status_counts':dict(Counter(r['primary_status'] for r in planned)),
                       'diagnostic_status_counts':dict(Counter(r['diagnostic_status'] for r in planned)),
                       'by_recovery_class':byclass}
    return panels

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',default='results/diagnostics/m4_main_v12_001')
    args=parser.parse_args();folder=(ROOT/args.run).resolve()
    if not folder.is_relative_to(ROOT/'results/diagnostics'):parser.error('Only the project offline diagnostic scope is supported')
    manifest_path=folder/'manifest.json';manifest=read(manifest_path)
    diag_summary=read(folder/'analysis/summary.json');diagnoses=read(folder/'analysis/query_diagnostics.json')
    if diag_summary['manifest_sha256']!=sha(manifest_path) or diag_summary['integrity_issues']:
        raise RuntimeError('Diagnosis aggregation is stale or failed its integrity checks')
    if diag_summary.get('derived_view_sha256',{}).get('query_diagnostics.json')!=sha(folder/'analysis/query_diagnostics.json'):
        raise RuntimeError('Diagnostic query rows changed after aggregation; refresh the derived summary')
    for name,expected in diag_summary['input_sha256'].items():
        if sha(ROOT/name)!=expected:raise RuntimeError('Diagnostic input bytes changed after aggregation')
    queries=manifest['frozen']['queries']
    lookup=validate_query_rows(queries,diagnoses)
    if set(manifest['frozen']['upstream_manifests'])!={q['upstream_run'] for q in queries}:
        raise RuntimeError('Upstream manifest set differs from the diagnostic query plan')
    tables={};provenance={};rows=[]
    for run in sorted({q['upstream_run'] for q in queries}):
        directory=ROOT/run;summary=read(directory/'summary.json');plan=read(directory/'manifest.json')
        if manifest['frozen']['upstream_manifests'][run]!=sha(directory/'manifest.json'):
            raise RuntimeError('Primary manifest differs from the frozen diagnostic upstream')
        if summary['run_manifest_sha256']!=sha(directory/'manifest.json'):raise RuntimeError('Primary summary manifest differs')
        if summary.get('derived_view_sha256',{}).get('query_results.csv')!=sha(directory/'query_results.csv'):
            raise RuntimeError('Primary query CSV changed after aggregation; refresh its derived summary')
        actual=list(csv.DictReader((directory/'query_results.csv').open()))
        mainrows=[r for r in actual if r['method']=='zrhfd' and r['setting']=='no_volume' and r['variant']=='main']
        mapping={r['task']:r for r in mainrows}
        if len(mapping)!=len(mainrows):raise RuntimeError('Duplicate primary main task')
        expected={q['task'] for q in queries if q['upstream_run']==run}
        if set(mapping)!=expected:raise RuntimeError('Primary CSV does not contain exactly the planned main queries')
        if not expected.issubset({Path(path).stem for path in plan['jobs']}):
            raise RuntimeError('Diagnosis plan is not contained in the primary job manifest')
        tables[run]=(mapping,summary)
        provenance[run]={'manifest_sha256':sha(directory/'manifest.json'),'summary_sha256':sha(directory/'summary.json'),
                         'query_csv_sha256':sha(directory/'query_results.csv'),'planned_main_rows':len(mainrows),
                         'implementation_versions':sorted({r['implementation_exact_cut_backend'] for r in mainrows})}
    for q in queries:
        diagnostic=lookup[q['diagnostic_query_id']];table,summary=tables[q['upstream_run']]
        if q['split']=='test' and type(diagnostic.get('diagnostic_scope_allowed')) is not bool:
            raise RuntimeError('Test diagnostic rows must explicitly declare scope authorization')
        primary=table[q['task']]
        if sha(ROOT/q['job_path'])!=q['job_sha256']:
            raise RuntimeError('Query/job identity differs from frozen diagnosis plan')
        job=read(ROOT/q['job_path'])
        validate_primary_identity(primary,q,job)
        done=primary['status']=='COMPLETED' and primary['completion_claim']=='True'
        f1=float(primary['F1']) if done else None
        if f1 is not None and (not math.isfinite(f1) or not 0<=f1<=1):raise RuntimeError('Invalid completed F1')
        raw_sha=None
        if done:
            if primary['raw_path']!=q['raw_path']:raise RuntimeError('Primary raw path differs')
            raw_sha=sha(ROOT/q['raw_path'])
            if summary['raw_sha256'].get(q['raw_path'])!=raw_sha:raise RuntimeError('Primary raw bytes changed')
        if diagnostic.get('attempt'):
            receipt=ROOT/diagnostic['attempt']/'receipt.json'
            if receipt.exists():
                relative=str(receipt.relative_to(ROOT))
                if diag_summary['input_sha256'].get(relative)!=sha(receipt):
                    raise RuntimeError('Offline diagnostic receipt changed after aggregation')
                terminal=read(receipt)
                if raw_sha is not None and terminal.get('source_raw_sha256')!=raw_sha:
                    raise RuntimeError('Offline diagnosis was not computed from this primary result')
            elif diagnostic.get('static_exact_available'):
                raise RuntimeError('Static diagnosis lacks a terminal receipt binding its source')
        recovery=classify(primary,diagnostic);comparison=None
        if recovery=='H2' and diagnostic.get('Z_output_minus_truth_exact') is not None:
            delta=Fraction(diagnostic['Z_output_minus_truth_exact'])
            comparison='output_has_lower_Z_than_truth' if delta<0 else 'feasible_truth_has_lower_Z_than_output' if delta>0 else 'output_ties_truth_Z'
        row={'diagnostic_query_id':q['diagnostic_query_id'],'task':q['task'],'split':q['split'],'case_id':q['case_id'],
             'seed':q['seed'],'primary_status':primary['status'],'primary_completion_claim':done,'F1':f1,
             'recovery_class':recovery,'diagnostic_status':diagnostic['diagnostic_status'],
             'diagnostic_scope_allowed':diagnostic.get('diagnostic_scope_allowed',q['split']=='dev'),
             'diagnostic_scope_reason':diagnostic.get('diagnostic_scope_reason'),
             'static_exact_available':diagnostic.get('static_exact_available',False),'C_subset_R':diagnostic.get('C_subset_R'),
             'finite_numeric_m_c_completed':diagnostic.get('finite_numeric_m_c_completed',False),
             'm_c_over_m_jstar_plus1':diagnostic.get('m_c_over_m_jstar_plus1'),'rho_hat':diagnostic.get('rho_hat'),
             'outside_volume_ratio':diagnostic.get('outside_volume_ratio'),'single_step_margin_min_exact':diagnostic.get('single_step_margin_min_exact'),
             'single_step_margin_negative_fraction':diagnostic.get('single_step_margin_negative_fraction'),
             'Z_output_minus_truth_exact':diagnostic.get('Z_output_minus_truth_exact'),'H2_objective_comparison':comparison,
             'j_act':primary['j_act'],'m_act':primary['m_act'],'output_size':primary['size_out'],
             'primary_raw_sha256':raw_sha,'upstream_run':q['upstream_run']}
        rows.append(row)
    output=folder/'analysis';table=output/'quality_failure_crosslist.csv'
    with table.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    result={'schema_version':1,'planned_queries':768,'diagnostic_manifest_sha256':sha(manifest_path),
            'diagnostic_summary_sha256':sha(folder/'analysis/summary.json'),'diagnostic_rows_sha256':sha(folder/'analysis/query_diagnostics.json'),
            'primary_runs':provenance,'panels':summarize(rows),'crosslist_sha256':sha(table),'join_source_sha256':sha(__file__),
            'diagnostic_scope':diag_summary.get('diagnostic_scope'),
            'truth_use':'offline diagnosis and evaluation only; no method/parameter changes',
            'scope':'All planned queries; absent quality stays null. Objective comparison uses exact Z differences, not penalty-adjusted margin signs. No bootstrap or new diffusion.'}
    (output/'quality_failure_crosslist_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'joined':768,'panels':result['panels']},ensure_ascii=False))

if __name__=='__main__':main()
