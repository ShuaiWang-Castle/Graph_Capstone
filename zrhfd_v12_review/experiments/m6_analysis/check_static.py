"""Tiny stdlib fixtures for independent M6 audit arithmetic and receipt gates."""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import tempfile
import sys
import ast
import csv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.m6_analysis import audit as module


def npy(path, values, dtype):
    fmt = {"<i4": "i", "<i8": "q", "<f8": "d"}[dtype]
    header = repr({"descr": dtype, "fortran_order": False, "shape": (len(values),)})
    header += " " * ((64 - (10 + len(header) + 1) % 64) % 64) + "\n"
    path.write_bytes(b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header.encode() + struct.pack("<" + fmt * len(values), *values))


def checks():
    count = 0
    def require(value):
        nonlocal count
        assert value; count += 1
    def reject(function):
        nonlocal count
        try:
            function()
        except (ValueError, IndexError):
            count += 1
        else:
            raise AssertionError("Invalid artificial input was accepted")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        arrays = {}
        for key, values, dtype in (("ptr", [0, 2, 4, 6, 8], "<i8"),
                ("indices", [1, 3, 0, 2, 1, 3, 0, 2], "<i4"),
                ("weights", [1.0] * 8, "<f8"), ("degree", [2.0] * 4, "<f8")):
            path = root / (key + ".npy"); npy(path, values, dtype); arrays[key] = module.NpyArray(path)
        try:
            require(arrays["indices"][3] == 2 and arrays["degree"][0] == 2 and len(arrays["ptr"]) == 5)
            reject(lambda: arrays["indices"][-1])
            reject(lambda: arrays["indices"][8])
            require(module.set_stats({0}, **arrays, total=8) == {"volume": 2, "cut": 2, "Z": 1.25, "Z_exact": "5/4", "phi": 1., "phi_v": 1., "size": 1})
            require(module.set_stats({0, 1}, **arrays, total=8)["Z_exact"] == "1")
            require(module.quality({0}, {0, 1}) == {"precision": 1., "recall": .5, "F1": 2/3, "symmetric_difference": 1})
            require(module.quality(set(), {0, 1})["F1"] == 0.)
            query = {"n": 4, "seed": 0, "offline_only": {"community_index": 0}}
            output = {"vertices": [0], "region_vertices": [0, 1], "certificate": {"hull_best": [0, 1]},
                      "touched_vertices": [0, 1, 2, 3], "touched_volume": 8., "region_volume": 4.,
                      "stats": module.set_stats({0}, **arrays, total=8)}
            offline = module.independent_offline(query, output, [[0, 1], [2, 3]], arrays, 8)
            require(offline["covered"] and offline["failure_class"] == "H2" and offline["quality"]["F1"] == 2/3 and offline["hull_best_quality"]["F1"] == 1.)
            require(offline["rho_hat"] == 0 and offline["target_volume"] == 4 and offline["touched_over_output_volume"] == 4)
            h1 = {**output, "region_vertices": [0], "region_volume": 2., "certificate": {"hull_best": [0]}, "touched_vertices": [0, 1], "touched_volume": 4.}
            h1_offline = module.independent_offline(query, h1, [[0, 1], [2, 3]], arrays, 8)
            require(h1_offline["failure_class"] == "H1" and not h1_offline["covered"] and h1_offline["region_missing_truth_vertices"] == [1])
            recovered = {**output, "vertices": [0, 1], "region_vertices": [0, 1, 2], "region_volume": 6., "stats": module.set_stats({0, 1}, **arrays, total=8)}
            recovered_offline = module.independent_offline(query, recovered, [[0, 1], [2, 3]], arrays, 8)
            require(recovered_offline["quality"]["F1"] == 1 and recovered_offline["failure_class"] is None and recovered_offline["rho_hat"] == .5 and recovered_offline["region_outside_truth_volume_ratio"] == .5)
            reject(lambda: module.independent_offline(query, {**output, "vertices": [0, 2]}, [[0, 1], [2, 3]], arrays, 8))
            reject(lambda: module.independent_offline(query, {**output, "touched_volume": 7}, [[0, 1], [2, 3]], arrays, 8))
            reject(lambda: module.independent_offline(query, output, [[0, 1], []], arrays, 8))
            reject(lambda: module.vertices([0, 0], 4, "duplicates"))
            reject(lambda: module.vertices([True], 4, "boolean vertex"))
        finally:
            for array in arrays.values(): array.close()
        q = {"query_id": "artificial_q00", "case_id": "artificial", "n": 10000, "generation_seed": 1, "seed": 0}
        config = {"implementation_version": module.VERSION}
        pending = module.projected_row(q, config, 0)
        require(pending["status"] == "NOT_RUN" and "F1" not in pending)
        partial = module.projected_row(q, config, 1, "results/artificial/attempt_000")
        require(partial["status"] == "interrupted_unfinished" and "F1" not in partial)
        terminal = {"status": "timeout", "runtime_censored": True, "parent_process_wall_seconds": 600.1, "last_checkpoint": {"event": {"stage": "certificate_started"}}}
        failed = module.projected_row(q, config, 1, "results/artificial/attempt_000", terminal)
        require(failed["runtime_censored"] and failed["last_checkpoint_stage"] == "certificate_started" and "F1" not in failed)
        rows = [{key: "" if value is None else str(value) for key, value in failed.items()}]
        module.compare_csv(rows, [failed]); count += 1
        reject(lambda: module.compare_csv([{**rows[0], "seed": "1"}], [failed]))
        reject(lambda: module.compare_csv([{**rows[0], "parent_process_wall_seconds": "2"}], [failed]))
        reject(lambda: module.compare_csv([rows[0], rows[0]], [failed, failed]))
        reject(lambda: module.compare_csv([{**rows[0], "F1": "1"}], [failed]))
        reject(lambda: module.portable(root, "../outside"))
        reject(lambda: module.portable(root, "/absolute"))
        receipt = root / "receipt.json"; receipt.write_text('{}')
        reject(lambda: module.verify_audit_receipt(receipt))
        # Complete 108-identity receipt with no attempts or quality. Only tiny
        # artificial source/metadata files; no actual cohort files are opened.
        schedule = [{"query_id": f"case_{n}_{seed}_q{i:02d}", "case_id": f"case_{n}_{seed}",
            "n": n, "generation_seed": seed, "seed": i} for n in (10000, 100000, 1000000) for seed in range(3) for i in range(12)]
        config = {"implementation_version": module.VERSION}
        def save(name, value):
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value)); return path
        save(module.CONFIG, config)
        source = (ROOT / "experiments/m6_analysis/audit.py").read_text()
        for name in module.SOURCES - {module.CONFIG}:
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('artificial source bytes')
        auditor = root / 'experiments/m6_analysis/audit.py'; auditor.parent.mkdir(parents=True, exist_ok=True); auditor.write_text(source)
        sources = {name: module.sha(root / name) for name in module.SOURCES}
        manifest = {"source_sha256": sources, "configuration": config, "config_sha256": module.sha(root / module.CONFIG),
            "implementation_version": module.VERSION, "source_state": "SOURCE_FROZEN", "legacy_measurements_imported": False,
            "dependency_fingerprint": {}, "schedule": schedule}
        run = root / 'results/m6_prepared'
        save('results/m6_prepared/manifest.json', manifest)
        summary = {"completed_queries": 0, "status_counts": {"NOT_RUN": 108}}
        save('results/m6_prepared/summary.json', summary)
        projections = [module.projected_row(q, config, 0) for q in schedule]
        csv_path = run / 'query_summary.csv'
        with csv_path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(projections[0])); writer.writeheader(); writer.writerows(projections)
        file_names = list(sources) + ['results/m6_prepared/manifest.json', 'results/m6_prepared/summary.json', 'results/m6_prepared/query_summary.csv']
        payload = {"schema_version": 1, "status": "PASS", "cohort_origin": "ORIGINAL_FROZEN_COHORT", "run_path": "results/m6_prepared",
            "implementation_version": module.VERSION, "scheduled_queries": 108, "completed_queries": 0, "all_queries_completed": False,
            "status_counts": {"NOT_RUN": 108}, "manifest_sha256": module.sha(run / 'manifest.json'), "summary_sha256": module.sha(run / 'summary.json'),
            "query_csv_sha256": module.sha(csv_path), "config_sha256": module.sha(root / module.CONFIG), "source_sha256": sources,
            "dependency_fingerprint": {}, "auditor_source_sha256": module.sha(auditor), "query_records": projections,
            "attempt_records": [], "completed_quality_checks": [], "validated_files_sha256": {name: module.sha(root / name) for name in file_names},
            "algorithm_or_numpy_imported": False, "measurement_sources_inputs_raw_or_timers_modified": False}
        def receipt_save(value):
            value = dict(value); value['receipt_payload_sha256'] = module.object_sha({k:v for k,v in value.items() if k!='receipt_payload_sha256'})
            return save('results/m6_analysis/prepared_audit/receipt.json', value)
        receipt_path = receipt_save(payload)
        verified = module.verify_audit_receipt(receipt_path, run_path=run, verify_files=True)
        require(verified['status']=='PASS' and verified['scheduled_queries']==108 and verified['completed_queries']==0)
        require(verified['all_queries_completed'] is False and verified['files_reverified_now'] is True)
        receipt_save({**payload, 'query_records': projections[:-1]})
        reject(lambda: module.verify_audit_receipt(receipt_path))
        receipt_save({**payload, 'source_sha256': {}})
        reject(lambda: module.verify_audit_receipt(receipt_path))
        receipt_save({**payload, 'completed_queries': 1})
        reject(lambda: module.verify_audit_receipt(receipt_path))
        receipt_save({**payload, 'cohort_origin': 'FRESH_REPRODUCTION'})
        reject(lambda: module.verify_audit_receipt(receipt_path))
        dirty = [{**projections[0], 'F1': 1.0}] + projections[1:]
        receipt_save({**payload, 'query_records': dirty})
        reject(lambda: module.verify_audit_receipt(receipt_path))
        # One completed artificial receipt row tests only metadata correlation,
        # not a claimed real algorithm run or independent truth recomputation.
        done_rows = json.loads(json.dumps(projections)); first = done_rows[0]
        attempt = f"results/m6_prepared/queries/{first['query_id']}/attempt_000"
        first.update(status='completed', attempt_count=1, raw_directory=attempt, F1=.5, hull_best_F1=.75, covered=True, failure_class='H2')
        def write_csv(rows):
            with csv_path.open('w', newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=sorted({key for row in rows for key in row}));writer.writeheader();writer.writerows(rows)
        write_csv(done_rows)
        save('results/m6_prepared/summary.json', {'completed_queries':1,'status_counts':{'completed':1,'NOT_RUN':107}})
        attempt_hashes = {}
        for name in ('request.json','terminal.json','result.json'):
            path=save(attempt+'/'+name, {'artificial_metadata_only': True});attempt_hashes[name]=module.sha(path)
        quality_check={'query_id':first['query_id'],'attempt':attempt,'F1':.5,'hull_F1':.75,'C_subset_R':True,'failure_class':'H2'}
        done_payload={**payload,'query_records':done_rows,'completed_queries':1,'status_counts':{'completed':1,'NOT_RUN':107},
            'completed_quality_checks':[quality_check],'summary_sha256':module.sha(run/'summary.json'),'query_csv_sha256':module.sha(csv_path),
            'attempt_records':[{'query_id':first['query_id'],'directory':attempt,'status':'completed','artifact_sha256':attempt_hashes}]}
        done_payload['validated_files_sha256']={**payload['validated_files_sha256'],
            'results/m6_prepared/summary.json':done_payload['summary_sha256'],'results/m6_prepared/query_summary.csv':done_payload['query_csv_sha256'],
            **{attempt+'/'+name:digest for name,digest in attempt_hashes.items()}}
        receipt_save(done_payload);require(module.verify_audit_receipt(receipt_path,verify_files=True)['completed_queries']==1)
        receipt_save({**done_payload,'completed_quality_checks':[{**quality_check,'query_id':'wrong'}]})
        reject(lambda: module.verify_audit_receipt(receipt_path))
        receipt_save({**done_payload,'completed_quality_checks':[{**quality_check,'F1':1.0}]})
        reject(lambda: module.verify_audit_receipt(receipt_path))
        receipt_save({**done_payload,'completed_quality_checks':[{**quality_check,'attempt':'results/elsewhere'}]})
        reject(lambda: module.verify_audit_receipt(receipt_path))
        receipt_save({**done_payload,'attempt_records':[]})
        reject(lambda: module.verify_audit_receipt(receipt_path))
        receipt_save({**done_payload,'query_records':[{**first,'F1':.6}]+done_rows[1:]})
        reject(lambda: module.verify_audit_receipt(receipt_path))
        save('results/m6_prepared/summary.json', summary)
        with csv_path.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(projections[0]));writer.writeheader();writer.writerows(projections)
        receipt_save(payload); csv_path.write_text(csv_path.read_text()+'changed')
        reject(lambda: module.verify_audit_receipt(receipt_path))
        tree = ast.parse(source)
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        require(not any(name and name.split('.')[0] in {'numpy', 'numba', 'scipy', 'matplotlib', 'zrhfd'} for name in imports))
        require(all(name not in sys.modules for name in ('numpy', 'numba', 'scipy', 'matplotlib', 'zrhfd')))
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="reviews/m6_analysis/STDLIB_TINY_v004.json")
    args = parser.parse_args()
    target = (ROOT / args.output).resolve()
    if not target.is_relative_to(ROOT / "reviews/m6_analysis"):
        parser.error("Fixture evidence stays in reviews/m6_analysis")
    value = {"status": "PASS_STDLIB_TINY_ARITHMETIC_AND_SCHEMA", "checks": checks(),
             "actual_truth_graph_raw_or_summary_read": False, "algorithm_or_numpy_or_matplotlib_imported": False,
             "full108_cohort_audit": "NOT_RUN", "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                 for name in ("experiments/m6_analysis/audit.py", "experiments/m6_analysis/check_static.py")}}
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x") as stream: json.dump(value, stream, indent=2); stream.write("\n")
    print(json.dumps({"status": value["status"], "checks": value["checks"], "receipt": str(target.relative_to(ROOT))}))


if __name__ == '__main__': main()
