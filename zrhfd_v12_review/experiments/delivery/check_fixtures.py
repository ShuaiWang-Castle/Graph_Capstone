#!/usr/bin/env python3
"""Tiny stdlib fixtures only; no project data reads or real experiment execution."""
import hashlib
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import warnings
from unittest.mock import patch
import zipfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("delivery_package", HERE / "package.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def run():
    checks = []

    def check(name, predicate):
        if not predicate:
            raise AssertionError(name)
        checks.append({"name": name, "status": "PASS"})

    def rejects(name, f):
        try:
            f()
        except (ValueError, FileExistsError, zipfile.BadZipFile, KeyError, FileNotFoundError):
            checks.append({"name": name, "status": "PASS"})
        else:
            raise AssertionError(name)

    with tempfile.TemporaryDirectory(prefix="zrhfd_delivery_tiny_") as tmp:
        root = Path(tmp)
        def put(rel, text):
            q = root / rel
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_text(text)
            return q
        denied = hashlib.sha256(b"author restricted source\n").hexdigest()
        paper = hashlib.sha256(b"original PDF fixture\n").hexdigest()
        lock = {"repositories": {key: {"url": "https://example.invalid/" + key,
                  "commit": "fixture", "tracked_worktree_file_sha256": {"original.jl": denied}}
                  for key in ("hfd", "pnormflowdiffusion")},
                "papers": {name: {"url": "https://example.invalid/paper/" + name, "path": name + ".pdf", "sha256": paper} for name in p.REQUIRED_PAPER_PINS}}
        put("experiments/reproduction/lock.json", json.dumps(lock))
        put("REPORT.md", "Documented FAIL and STOPPED; no success claim.\n")
        put("results/failed/receipt.json", '{"status":"TIMEOUT"}\n')
        put("results/failed/checkpoint.json", '{"completed_trials":1}\n')
        put("zrhfd/model.py", "print('fixture')\n")
        put("inputs/local_hfd/graphs/lfr_n1000_o00_m20_s11.graph.json", '{"fixture":true}\n')
        put("data/dev/generated.graph.json", '{"large_input_fixture":true}\n')
        put("data/dev/catalog.json", '{"hash":"existing receipt"}\n')
        put("results/source_snapshot/sources/external/hfd/a.jl", "author restricted source\n")
        put("results/source_snapshot/renamed.jl", "author restricted source\n")
        put("results/source_snapshot/renamed.pdf", "original PDF fixture\n")
        put("results/numba_cache/example.nbi", "compiled fixture\n")
        put("external/runtime/fixture", "excluded without scan\n")
        put("data/external/benson-downloads/fixture", "excluded official raw\n")
        put("results/failure.stderr.log", "failure fixture retained\n")
        put("results/storage_fixtures/deliberate_bad/corrupt.zip", "not a ZIP, artificial registered payload\n")
        put("results/storage_fixtures/deliberate_bad/ARCHIVE.json", "deliberately invalid fixture index\n")
        put("results/storage_fixtures/deliberate_bad/checks.json", '{"synthetic_only":true,"status":"PASS"}\n')
        science_dir = root / "results/m5/frozen/queries/task_fixture/attempt_000"
        partial_path = "progress/.000001.json.partial-fixture"
        partial_bytes = b'{"event":"truncated and uncompleted'
        terminal_path = put("results/m5/frozen/queries/task_fixture/attempt_000/receipt.json", '{"status":"TIMEOUT"}\n')
        expanded_partial = science_dir / partial_path
        expanded_partial.parent.mkdir(parents=True)
        expanded_partial.write_bytes(partial_bytes)
        science_raw = science_dir / "RAW_RECORDS.zip"
        with zipfile.ZipFile(science_raw, "x") as z:
            z.writestr(partial_path, partial_bytes)
        science_audit = p.zip_audit(science_raw, {})
        science_index = {"archive":"RAW_RECORDS.zip", "archive_sha256":p.sha_file(science_raw),
            "terminal_status":"TIMEOUT", "terminal_receipt_sha256":p.sha_file(terminal_path),
            "files":{x["path"]:{"sha256":x["sha256"],"bytes":x["size"]} for x in science_audit["members"]}}
        (science_dir / "ARCHIVE.json").write_text(json.dumps(science_index))
        science_container = root / "results/scientific_nested_bundle.zip"
        with zipfile.ZipFile(science_container, "x") as z:
            z.writestr("task/RAW_RECORDS.zip", science_raw.read_bytes())
            z.writestr("task/ARCHIVE.json", json.dumps(science_index))
            z.writestr("task/receipt.json", terminal_path.read_bytes())
        put("results/loose.partial-fixture", "temporary outside terminal scientific attempt\n")
        archive = root / "results/failed/raw.zip"
        with zipfile.ZipFile(archive, "x") as z:
            z.writestr("trial_0/checkpoint.json", '{"state":"partial"}\n')
            z.writestr("RAW_INDEX.json", '{"members":["trial_0/checkpoint.json"]}\n')
        original_audit = p.zip_audit(archive, {})
        original_index = {"archive": "raw.zip", "archive_sha256": p.sha_file(archive),
                          "files": {x["path"]: {"sha256": x["sha256"], "bytes": x["size"], "zip_compression_method": x["compression_method"]} for x in original_audit["members"]}}
        put("results/failed/ARCHIVE.json", json.dumps(original_index))
        mixed_archive = root / "results/mixed_codecs.zip"
        with zipfile.ZipFile(mixed_archive, "x") as z:
            z.writestr("large_plaintext.log", b"tiny LZMA fixture\n" * 3, compress_type=zipfile.ZIP_LZMA)
            z.writestr("small.json", b'{"tiny":true}\n', compress_type=zipfile.ZIP_DEFLATED)
            z.writestr("encoded.bin", b"already encoded fixture", compress_type=zipfile.ZIP_STORED)
        mixed_audit = p.zip_audit(mixed_archive, {})
        check("native_lzma_deflate_store_mixed_members_stream_checked", mixed_audit["crc_and_sha_verified"] and mixed_audit["member_count"] == 3)
        status = {"schema": "zrhfd-delivery-status-v1", "decision_by": "root", "status": "STOPPED",
                  "measurement_closed": True, "written_conclusion": "Documented numerical FAIL; delivery allowed.",
                  "conclusion_files": ["REPORT.md"]}
        put("DELIVERY_STATUS.json", json.dumps(status))
        inv = p.inventory(root)
        paths = {x["path"] for x in inv["included"]}
        check("metadata_only_no_hash_or_zip_reads", not inv["raw_file_hashing_performed"] and not inv["zip_opened"] and all("sha256" not in x for x in inv["included"]))
        check("failed_partial_stderr_and_original_nested_archive_retained", {"results/failed/receipt.json", "results/failed/checkpoint.json", "results/failure.stderr.log", "results/failed/raw.zip"} <= paths)
        check("author_runtime_cache_excluded_at_any_snapshot_depth", not any("/hfd/" in x or "numba_cache" in x or "external/runtime" in x for x in paths))
        check("user_attached_graph_retained_and_generated_graph_omitted", "inputs/local_hfd/graphs/lfr_n1000_o00_m20_s11.graph.json" in paths and "data/dev/generated.graph.json" not in paths)
        check("registered_bad_synthetic_payload_omitted_but_checks_retained", "results/storage_fixtures/deliberate_bad/checks.json" in paths and "results/storage_fixtures/deliberate_bad/corrupt.zip" not in paths and "results/storage_fixtures/deliberate_bad/ARCHIVE.json" not in paths)
        check("expanded_terminal_scientific_hidden_partial_retained", expanded_partial.relative_to(root).as_posix() in paths)
        check("unscoped_temporary_partial_remains_excluded", "results/loose.partial-fixture" not in paths)
        state = p.validate_status(root)
        check("root_stopped_fail_written_decision_deliverable", state["decision"]["status"] == "STOPPED")
        put("DELIVERY_STATUS.json", json.dumps({**status, "measurement_closed": False}))
        rejects("active_status_rejected", lambda: p.validate_status(root))
        put("DELIVERY_STATUS.json", json.dumps({**status, "written_conclusion": " "}))
        rejects("empty_written_conclusion_rejected", lambda: p.validate_status(root))
        put("DELIVERY_STATUS.json", json.dumps(status))
        inv = p.inventory(root)
        state = p.validate_status(root)
        out = root / "fixture.zip"
        manifest = p.create_zip(root, inv, out, state, check_gate=False)
        verified = p.verify_zip(out)
        check("all_payload_and_nested_member_sha_verified", verified["verified"] and verified["nested_raw_archive_count"] == 4)
        with zipfile.ZipFile(out) as z:
            check("lzma_nested_archive_bytes_preserved_and_outer_stored", z.read("results/mixed_codecs.zip") == mixed_archive.read_bytes() and z.getinfo("results/mixed_codecs.zip").compress_type == zipfile.ZIP_STORED)
        check("renamed_restricted_source_and_paper_content_omitted", {x["path"] for x in manifest["content_excluded"]} == {"results/source_snapshot/renamed.jl", "results/source_snapshot/renamed.pdf"})
        check("omitted_input_stream_sha_recorded", manifest["omitted_input_stream_sha256"][0]["sha256"] == p.sha_file(root / "data/dev/generated.graph.json"))
        nested = manifest["nested_raw_archives"]["results/failed/raw.zip"]
        check("nested_original_index_and_partial_members_preserved", {x["path"] for x in nested["members"]} == {"RAW_INDEX.json", "trial_0/checkpoint.json"})
        check("existing_external_archive_index_member_sha_verified", manifest["original_raw_index_validation"][0]["original_index_member_sha_verified"])
        old_index = {**original_index, "files": {name: {k: v for k,v in record.items() if k != "zip_compression_method"} for name,record in original_index["files"].items()}}
        old_entries = [x for x in manifest["included"] if x["path"].startswith("results/failed/")]
        check("old_v1_index_without_compression_fields_supported", bool(p.audit_storage_indexes(old_entries, {"results/failed/raw.zip":manifest["nested_raw_archives"]["results/failed/raw.zip"]}, lambda _: json.dumps(old_index).encode())))
        wrong_method = {**original_index, "files": {name: {**record, "zip_compression_method": 99} for name,record in original_index["files"].items()}}
        rejects("v2_index_wrong_compression_method_rejected", lambda: p.audit_storage_indexes(old_entries, {"results/failed/raw.zip":manifest["nested_raw_archives"]["results/failed/raw.zip"]}, lambda _: json.dumps(wrong_method).encode()))
        with zipfile.ZipFile(out) as z:
            check("nested_archive_original_bytes_unchanged", z.read("results/failed/raw.zip") == archive.read_bytes())
            check("expanded_and_nested_scientific_partial_exact_bytes_retained", z.read(expanded_partial.relative_to(root).as_posix()) == partial_bytes and z.read(science_raw.relative_to(root).as_posix()) == science_raw.read_bytes())
        science = manifest["nested_raw_archives"][science_raw.relative_to(root).as_posix()]
        check("partial_raw_never_completion_claim", science["unpublished_partial_records"] == [partial_path] and science["partial_records_completion_claim"] is False)
        check("deep_scientific_partial_terminal_and_index_bound", len(manifest["nested_raw_archives"]["results/scientific_nested_bundle.zip"]["original_raw_index_validation"]) == 1)
        terminal_path.write_text('{"status":"ACTIVE"}\n')
        rejects("expanded_partial_requires_terminal_status", lambda: p.scientific_partial_receipt(expanded_partial, root, validate=True))
        invalid_terminal_bundle = io.BytesIO()
        with zipfile.ZipFile(invalid_terminal_bundle, "w") as z:
            z.writestr("task/RAW_RECORDS.zip", science_raw.read_bytes())
            z.writestr("task/ARCHIVE.json", json.dumps(science_index))
            z.writestr("task/receipt.json", terminal_path.read_bytes())
        invalid_terminal_bundle.seek(0)
        rejects("deep_indexed_partial_requires_original_terminal_receipt", lambda: p.zip_audit(invalid_terminal_bundle, {}))
        terminal_path.write_text('{"status":"TIMEOUT"}\n')
        stale = p.inventory(root)
        put("zrhfd/model.py", "changed fixture\n")
        bad = root / "bad-stale.zip"
        rejects("stale_inventory_refuses_and_preserves_partial_zip", lambda: p.create_zip(root, stale, bad, state, check_gate=False))
        check("bad_temporary_zip_not_deleted", bad.exists())
        unsafe = io.BytesIO()
        with zipfile.ZipFile(unsafe, "w") as z:
            z.writestr("../escape", b"bad")
        unsafe.seek(0)
        rejects("unsafe_nested_zip_rejected", lambda: p.zip_audit(unsafe, {}))
        restricted = io.BytesIO()
        with zipfile.ZipFile(restricted, "w") as z:
            z.writestr("renamed.jl", b"author restricted source\n")
        restricted.seek(0)
        rejects("restricted_nested_content_refused_without_mutating_raw", lambda: p.zip_audit(restricted, p.author_denied(root)))
        deep = io.BytesIO()
        with zipfile.ZipFile(deep, "w") as z:
            z.writestr("inner.zip", restricted.getvalue())
        deep.seek(0)
        rejects("restricted_deep_nested_content_also_refused", lambda: p.zip_audit(deep, p.author_denied(root)))
        deeper = io.BytesIO()
        with zipfile.ZipFile(deeper, "w") as z:
            z.writestr("task/RAW_RECORDS.zip", archive.read_bytes())
            z.writestr("task/ARCHIVE.json", json.dumps({**original_index, "archive": "RAW_RECORDS.zip"}))
        deeper.seek(0)
        check("deep_nested_raw_index_pair_verified", len(p.zip_audit(deeper, {})["original_raw_index_validation"]) == 1)
        bad_deep = io.BytesIO()
        with zipfile.ZipFile(bad_deep, "w") as z:
            z.writestr("task/RAW_RECORDS.zip", archive.read_bytes())
            z.writestr("task/ARCHIVE.json", json.dumps({**original_index, "archive": "RAW_RECORDS.zip", "archive_sha256": "0" * 64}))
        bad_deep.seek(0)
        rejects("bad_deep_nested_raw_index_sha_rejected", lambda: p.zip_audit(bad_deep, {}))
        rejects("corrupt_zip_rejected", lambda: p.zip_audit(io.BytesIO(b"not a ZIP"), {}))
        dup = io.BytesIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(dup, "w") as z:
                z.writestr("a", b"one")
                z.writestr("a", b"two")
        dup.seek(0)
        rejects("duplicate_nested_member_rejected", lambda: p.zip_audit(dup, {}))
        q = root / "exclusive.json"
        p.immutable_json(q, {"first": True})
        rejects("existing_json_not_overwritten", lambda: p.immutable_json(q, {"second": True}))
        check("existing_json_content_preserved", json.loads(q.read_text()) == {"first": True})
        downloads = root / "Downloads"
        downloads.mkdir()
        link = p.download_link(out, downloads)
        check("timestamp_downloads_same_inode_no_copy", link["status"] == "HARDLINK_CREATED" and link["same_inode"])
        check("live_process_detection_worker_relative_and_absolute", p.measurement_matches("python experiments/m5/worker.py --request a", root) and p.measurement_matches("python " + str(root / "experiments/m6_prepared/run.py") + " --run", root))
        check("live_module_invocation_detected", p.measurement_matches("python -m experiments.m5.worker --request a", root))
        check("delivery_and_other_commands_not_measurements", not p.measurement_matches("python experiments/delivery/package.py --create", root) and not p.measurement_matches("some unrelated 'unclosed command", root))
        rejects("existing_zip_exclusive_not_overwritten", lambda: p.create_zip(root, p.inventory(root), out, state, check_gate=False))
        p.immutable_json(root / "results/index_test.json", {"fixture": True})
        corrupted_index = {**original_index, "archive_sha256": "0" * 64}
        put("results/failed/ARCHIVE.json", json.dumps(corrupted_index))
        rejects("raw_archive_index_sha_disagreement_rejected", lambda: p.create_zip(root, p.inventory(root), root / "bad-index.zip", state, check_gate=False))
        put("results/failed/ARCHIVE.json", json.dumps(original_index))
        changed = root / "changed-payload.zip"
        with zipfile.ZipFile(out) as source, zipfile.ZipFile(changed, "x") as target:
            for info in source.infolist():
                content = source.read(info.filename)
                target.writestr(info.filename, content + b"tamper" if info.filename == "REPORT.md" else content)
        rejects("delivery_payload_sha_tamper_rejected", lambda: p.verify_zip(changed))
        with patch.object(p, "sha_file", side_effect=AssertionError("default CLI must not hash")), patch.object(p.zipfile, "ZipFile", side_effect=AssertionError("default CLI must not open ZIP")), contextlib.redirect_stdout(io.StringIO()):
            p.main(["--root", str(root), "--inventory-output", str(root / "metadata-only.json")])
        check("default_whole_cli_no_file_hash_or_zip_open", json.loads((root / "metadata-only.json").read_text())["operation"] == "metadata_inventory_only")
        with patch.object(p, "live_measurements", return_value=[{"pid": 999999, "command": "fixture measurement"}]):
            rejects("whole_gate_refuses_live_measurement", lambda: p.gate(root))
        original_report = (root / "REPORT.md").read_text()
        put("REPORT.md", "changed conclusion fixture\n")
        with patch.object(p, "live_measurements", return_value=[]):
            rejects("changed_conclusion_pin_refused", lambda: p.gate(root, state["status_sha256"], state["conclusion_sha256"]))
        put("REPORT.md", original_report)
        with patch.object(p, "live_measurements", return_value=[]), contextlib.redirect_stdout(io.StringIO()):
            p.main(["--root", str(root), "--create", "--downloads", str(downloads)])
        check("whole_create_cli_publishes_verified_canonical_and_receipt", (root / "DELIVERY.zip").is_file() and p.verify_zip(root / "DELIVERY.zip")["verified"] and len(list((root / "reviews/delivery").glob("creation_*/receipt.json"))) == 1)
        canonical_hash = p.sha_file(root / "DELIVERY.zip")
        with patch.object(p, "live_measurements", return_value=[]):
            rejects("whole_create_cli_refuses_existing_canonical", lambda: p.main(["--root", str(root), "--create"]))
        check("canonical_not_overwritten_by_second_create", p.sha_file(root / "DELIVERY.zip") == canonical_hash)
        put("experiments/reproduction/lock.json", json.dumps({"repositories": lock["repositories"]}))
        rejects("missing_paper_pin_blocked", lambda: p.author_denied(root))
        put("experiments/reproduction/lock.json", json.dumps({**lock, "papers": {k:v for k,v in lock["papers"].items() if k != "pnorm"}}))
        rejects("missing_one_required_paper_pin_blocked", lambda: p.author_denied(root))
        put("experiments/reproduction/lock.json", json.dumps({**lock, "papers": {**lock["papers"], "hfd": {"path":"hfd.pdf","url":"https://example.invalid"}}}))
        rejects("missing_required_paper_sha_blocked", lambda: p.author_denied(root))
    result = {"schema": "delivery-tiny-fixtures-v1", "created_utc": p.utc(), "status": "PASS",
              "fixture_only": True, "real_project_inventory_or_hashing_performed": False,
              "real_measurement_run": False, "checks": checks,
              "source_sha256": {"package.py": p.sha_file(HERE / "package.py"), "check_fixtures.py": p.sha_file(Path(__file__))}}
    target = HERE.parents[1] / "reviews/delivery" / ("tiny_fixtures_" + p.datetime.now(p.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    p.immutable_json(target, result)
    print(json.dumps({"status": "PASS", "checks": len(checks), "evidence": str(target)}))


if __name__ == "__main__":
    run()
