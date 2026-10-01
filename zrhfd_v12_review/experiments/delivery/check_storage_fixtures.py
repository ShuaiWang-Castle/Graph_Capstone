#!/usr/bin/env python3
"""Recreate storage boundary checks with artificial files only, no algorithms."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run():
    source = ROOT / "experiments/archival.py"
    checks = []
    with tempfile.TemporaryDirectory(prefix="zrhfd_storage_tiny_") as temporary:
        fixture_root = Path(temporary).resolve()
        (fixture_root / "experiments").mkdir()
        (fixture_root / "experiments/archival.py").write_bytes(source.read_bytes())
        (fixture_root / "experiments/run_m5_archived.py").write_bytes((ROOT / "experiments/run_m5_archived.py").read_bytes())
        spec = importlib.util.spec_from_file_location("delivery_tiny_storage", fixture_root / "experiments/archival.py")
        storage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(storage)

        def case(name, status, *, receipt=None):
            d = fixture_root / "results" / name
            d.mkdir(parents=True)
            (d / "receipt.json").write_text(json.dumps({"status": status} if receipt is None else receipt))
            (d / "trace.json").write_text('{"fixture":true}\n')
            return d

        def refused(name, directory):
            before = (directory / "trace.json").read_bytes()
            try:
                storage.archive_completed_attempt(directory)
            except (RuntimeError, TypeError, AttributeError):
                assert (directory / "trace.json").read_bytes() == before
                checks.append({"name": name, "status": "PASS", "expanded_preserved": True})
            else:
                raise AssertionError(name)

        for i, status in enumerate(("ACTIVE", "STARTING", "STARTED", "running", None, "UNKNOWN")):
            refused("refuse_active_unknown_" + str(status), case("reject_" + str(i), status))
        refused("refuse_non_dict_receipt", case("reject_list", None, receipt=[]))
        for status in sorted(storage.TERMINAL_STATUSES):
            d = case("accept_" + status, status)
            original = (d / "trace.json").read_bytes()
            metadata = storage.archive_completed_attempt(d)
            assert not (d / "trace.json").exists()
            assert storage.read_bytes(d / "trace.json") == original
            assert metadata["terminal_status"] == status and metadata["included_in_measurement_runtime"] is False
            checks.append({"name": "accept_" + status, "status": "PASS", "bytes_preserved": True})
        d = case("codec_mixed", "COMPLETED")
        files = {"large.json": b" " * 65536, "small.log": b"tiny\n", "encoded.gz": b"already-encoded-fixture"}
        for name, content in files.items():
            (d / name).write_bytes(content)
        metadata = storage.archive_completed_attempt(d)
        with zipfile.ZipFile(d / "RAW_RECORDS.zip") as z:
            for name, method in (("large.json",14),("small.log",8),("encoded.gz",0)):
                assert z.read(name) == files[name] and z.getinfo(name).compress_type == method
                assert metadata["files"][name]["zip_compression_method"] == method
                checks.append({"name": "codec_" + str(method), "status": "PASS", "original_bytes_preserved": True})
        (d / "trace.json").write_text('{"fixture":true}\n')
        (d / "receipt.json").write_text('{"status":"ACTIVE"}')
        refused("existing_index_active_refused_before_cleanup", d)
        (d / "receipt.json").write_text('{"status":"COMPLETED","changed":true}')
        refused("changed_terminal_receipt_sha_refused_before_cleanup", d)

    receipt = {"schema": "delivery-synthetic-storage-checks-v1", "status": "PASS",
               "created_utc": datetime.now(timezone.utc).isoformat(), "synthetic_only": True,
               "algorithm_calls": 0, "real_raw_hashing_or_compression": False,
               "registered_fixture_root": "results/storage_fixtures", "checks": checks,
               "source_sha256": {"experiments/archival.py":sha(source),
                   "experiments/run_m5_archived.py":sha(ROOT / "experiments/run_m5_archived.py"),
                   "experiments/delivery/check_storage_fixtures.py":sha(__file__)}}
    output = ROOT / "reviews/delivery" / ("storage_tiny_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    with output.open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"status":"PASS", "checks":len(checks), "evidence":str(output)}))


if __name__ == "__main__":
    run()
