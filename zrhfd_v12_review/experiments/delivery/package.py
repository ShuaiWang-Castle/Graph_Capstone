#!/usr/bin/env python3
"""Private evidence delivery; default only lists file metadata (no raw hashing)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone

SCHEMA = "zrhfd-private-delivery-v1"
MANIFEST = "DELIVERY_MANIFEST.json"
CHUNK = 1024 * 1024
ROOT_FILES = (
    "AGENTS.md", "CHANGELOG.md", "EXECUTION_STATE.json", "EXPERIMENT_PROTOCOL_ZH.md",
    "README.md", "REPORT.md", "REPRODUCE.sh", "RESUME.md", "THEORY_REQUESTS.md",
    "THIRD_PARTY_NOTICES.md", "DELIVERY_STATUS.json", "LICENSE", "LICENSE.md", "LICENSE.txt",
    "COPYING", "NOTICE", "pyproject.toml", "requirements.txt",
)
ALLOW_DIRS = (
    "zrhfd", "experiments", "tests", "results", "reviews", "provenance", "figures",
    "inputs/local_hfd", "data", "external/generators", "external/localgraphclustering",
    "external/leidenalg",
)
EXTERNAL_FILES = ("external/acquire_sources.py", "external/acquire_julia.py")
BLOCK_COMPONENTS = {
    ".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "runtime", "depot", "julia_depot", "compiled", "compiledcache", "numba_cache",
    "hfd", "pnormflowdiffusion", "native-tmp", "julia-tmp", "tmp", "temporary",
}
RAW_DATA_DIRS = {
    "data/external/benson-downloads", "data/external/contact-high-school",
    "data/external/contact-high-school-official", "data/external/trivago-clicks",
    "data/external/trivago-clicks-official",
}
DATA_META_NAMES = {"queries.json", "GENERATION_FREEZE.json", "README.md", "README.txt"}
DATA_META_PREFIXES = ("catalog", "generation", "validation", "receipt", "config", "freeze")
SYNTHETIC_FIXTURE_ROOTS = ("results/storage_fixtures",)
REQUIRED_PAPER_PINS = {"hfd", "tlhfd", "cfsp", "pnorm"}
TERMINAL_EVIDENCE_STATUSES = {"COMPLETED", "FAILED", "TIMEOUT", "MEMORY_LIMIT", "INTERRUPTED",
    "PARTIAL_TIMEOUT", "PARTIAL_UPDATE_BUDGET", "ABANDONED_PREVIOUS_RUN", "ERROR",
    "NOT_COMPLETED", "ABANDONED_PREVIOUS_DIAGNOSTIC"}
TEMP_SUFFIXES = (".tmp", ".temp", ".pyc", ".pyo", ".nbc", ".nbi", ".o", ".so", ".dylib")
MEASUREMENT_SCRIPTS = {
    "experiments/schedule.py", "experiments/worker.py", "experiments/run_m2.py",
    "experiments/run_m5_archived.py", "experiments/run_m6_compressed.py",
    "experiments/serial_workflow.py", "experiments/m6_prepared/run.py",
    "experiments/m6_prepared/worker.py", "experiments/m6/run.py", "experiments/m6/worker.py",
    "experiments/m5/run_serial.py", "experiments/m5/worker.py", "experiments/m5/run_hsbm_smoke.py",
    "experiments/diagnostics/run_m2_dev.py", "experiments/diagnostics/run_m4.py",
    "experiments/diagnostics/m4_worker.py", "experiments/data_generation/run_all.py",
    "experiments/baseline_integration/run_smoke.py",
}


def utc():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def sha_stream(stream, progress=None):
    h = hashlib.sha256()
    size = 0
    while True:
        data = stream.read(CHUNK)
        if not data:
            return h.hexdigest(), size
        h.update(data)
        size += len(data)
        if progress:
            progress()


def sha_file(path, progress=None):
    with Path(path).open("rb") as f:
        return sha_stream(f, progress)[0]


def immutable_json(path, value):
    """Exclusive hardlink publication prevents readers seeing a torn JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp-" + uuid.uuid4().hex)
    with tmp.open("xb") as f:
        f.write(encode(value))
        f.flush()
        os.fsync(f.fileno())
    try:
        os.link(tmp, path)
    finally:
        tmp.unlink()


def safe_member(name):
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and ".." not in p.parts and "\\" not in name and ":" not in name and not any(ord(c) < 32 for c in name) and p.as_posix() == name.rstrip("/")


def partial_evidence_name(name):
    return ".partial-" in name or name.endswith((".tmp", ".temp"))


def terminal_status(data):
    status = data.get("status") if isinstance(data, dict) else None
    if not isinstance(status, str) or status.upper() not in TERMINAL_EVIDENCE_STATUSES:
        raise ValueError("scientific unpublished partial lacks a valid terminal receipt")
    return status


def scientific_partial_receipt(path, root, *, validate=False):
    rel = path.relative_to(root)
    if not rel.parts or rel.parts[0] != "results" or "queries" not in rel.parts or not partial_evidence_name(path.name):
        return None
    for parent in path.parents:
        if parent == root:
            break
        if parent.name.startswith("attempt_"):
            for name in ("receipt.json", "terminal.json"):
                receipt = parent / name
                if receipt.is_file() and not receipt.is_symlink():
                    if validate:
                        terminal_status(json.loads(receipt.read_text()))
                    return receipt
    return None


def exclusion(rel, *, directory=False, scientific_partial=False):
    """Pure path policy, also applied inside source snapshots and nested ZIPs."""
    p = PurePosixPath(rel)
    if any(part in BLOCK_COMPONENTS for part in p.parts):
        return "runtime/cache/git or author repository without redistribution permission"
    if "papers" in p.parts and (directory or p.suffix.lower() == ".pdf"):
        return "primary-paper original PDF; URL/SHA receipts retained"
    data_rel = None
    if "data" in p.parts:
        data_rel = PurePosixPath(*p.parts[p.parts.index("data"):]).as_posix()
    if data_rel and any(data_rel == x or data_rel.startswith(x + "/") for x in RAW_DATA_DIRS):
        return "original official raw data; download receipts retained"
    if p.name.startswith("DELIVERY") and p.name != "DELIVERY_STATUS.json":
        return "delivery output/self recursion"
    if p.name == ".DS_Store" or ".compression-tmp" in p.name:
        return "temporary/hidden file"
    if (p.name.startswith(".") or partial_evidence_name(p.name)) and not (scientific_partial and partial_evidence_name(p.name)):
        return "temporary/hidden file"
    if p.name.endswith(TEMP_SUFFIXES) and not (scientific_partial and p.name.endswith((".tmp", ".temp"))):
        return "compiled cache/object or temporary file"
    if directory:
        return None
    if any(rel.startswith(base + "/") or ("/" + base + "/") in rel for base in SYNTHETIC_FIXTURE_ROOTS):
        if p.name == "checks.json" or p.suffix in (".py", ".md"):
            return None
        return "registered synthetic storage fixture payload (may intentionally contain invalid ZIP/index/receipt); checks and generator retained"
    if data_rel:
        if p.suffix in (".py", ".md", ".log") or p.name in DATA_META_NAMES or p.name.endswith(".queries.json"):
            return None
        if p.suffix == ".json" and p.name.lower().startswith(DATA_META_PREFIXES):
            return None
        return "generated/raw graph or hypergraph input; hash + generation/catalog retained"
    return None


def stat_record(path, rel):
    s = path.lstat()
    return {"path": rel, "size": s.st_size, "mtime_ns": s.st_mtime_ns,
            "mode": stat.S_IMODE(s.st_mode), "inode": s.st_ino, "device": s.st_dev}


def inventory(root):
    """Only lstat and traversal of explicit allowlists; no ZIP opens or raw reads."""
    root = Path(root).resolve()
    included, excluded, missing = [], [], []
    seen = set()

    def visit(path):
        rel = path.relative_to(root).as_posix()
        if rel in seen:
            return
        seen.add(rel)
        if path.is_symlink():
            excluded.append({"path": rel, "reason": "symlink not followed"})
            return
        isdir = path.is_dir()
        partial_receipt = scientific_partial_receipt(path, root) if not isdir else None
        reason = exclusion(rel, directory=isdir, scientific_partial=bool(partial_receipt))
        if reason:
            entry = {"path": rel, "reason": reason, "directory_pruned": isdir}
            if not isdir:
                entry.update(stat_record(path, rel))
            excluded.append(entry)
            return
        if isdir:
            for child in sorted(path.iterdir()):
                visit(child)
        elif path.is_file():
            included.append(stat_record(path, rel))
        else:
            excluded.append({"path": rel, "reason": "nonregular file"})

    for name in ROOT_FILES + EXTERNAL_FILES + ALLOW_DIRS:
        path = root / name
        if path.exists() or path.is_symlink():
            visit(path)
        else:
            missing.append(name)
    included.sort(key=lambda x: x["path"])
    folded = {}
    for x in included:
        key = x["path"].casefold()
        if key in folded:
            raise ValueError(f"case-insensitive ZIP path collision: {folded[key]}, {x['path']}")
        folded[key] = x["path"]
    return {"schema": SCHEMA, "created_utc": utc(), "operation": "metadata_inventory_only",
            "raw_file_hashing_performed": False, "zip_opened": False,
            "allowlisted_root_files": list(ROOT_FILES + EXTERNAL_FILES),
            "allowlisted_directories": list(ALLOW_DIRS),
            "default_pruned_paths": sorted(RAW_DATA_DIRS | {"external/hfd", "external/pnormflowdiffusion", "external/papers", "external/runtime", ".venv", ".git", "work"}),
            "block_components_at_any_depth": sorted(BLOCK_COMPONENTS),
            "outside_allowlist_policy": "excluded without recursive traversal",
            "synthetic_fixture_registry": {"roots": list(SYNTHETIC_FIXTURE_ROOTS),
                "science_measurement": False, "payload_policy": "exclude artificial payload artifacts; preserve checks.json and generator/readme",
                "generator": "experiments/delivery/check_storage_fixtures.py", "original_fixture_payload_modified": False},
            "scientific_partial_policy": "retain unpublished partial bytes under scientific queries/attempt_* with terminal receipt; never a completion claim; terminal schema validated at creation",
            "included": included, "excluded": excluded, "missing_allowlisted_paths": missing,
            "included_count": len(included), "included_logical_bytes": sum(x["size"] for x in included),
            "author_source_policy": "unlicensed originals and renamed SHA-identical copies excluded at creation; receipts retained",
            "private_delivery_only": True, "publication_authorized": False}


def author_denied(root):
    """Small existing JSON pins; do not walk the author repository or runtime."""
    p = Path(root) / "experiments/reproduction/lock.json"
    if not p.exists():
        raise ValueError("required author source pin file missing: experiments/reproduction/lock.json")
    d = json.loads(p.read_text())
    deny = {}
    for name in ("hfd", "pnormflowdiffusion"):
        repo = d.get("repositories", {}).get(name)
        if not isinstance(repo, dict) or not repo.get("url") or not repo.get("commit"):
            raise ValueError(f"missing author acquisition pin for {name}")
        hashes = repo.get("tracked_worktree_file_sha256", {})
        if not hashes:
            raise ValueError(f"missing original file hashes for {name}")
        for path, h in hashes.items():
            deny.setdefault(h, []).append({"repository": name, "original_path": path, "url": repo["url"], "commit": repo["commit"]})
    # Paper originals outside external/papers are caught by content identity too.
    papers = d.get("papers")
    if not isinstance(papers, dict) or not REQUIRED_PAPER_PINS <= set(papers):
        raise ValueError("required original primary-paper SHA/URL pins missing")
    for name, paper in papers.items():
        if not isinstance(paper, dict) or not paper.get("url") or not paper.get("path") or not isinstance(paper.get("sha256"), str) or len(paper["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in paper["sha256"]):
            raise ValueError(f"invalid original primary-paper pin: {name}")
        deny.setdefault(paper["sha256"], []).append({"original_paper": paper["path"], "url": paper["url"]})
    return deny


def validate_status(root):
    p = Path(root) / "DELIVERY_STATUS.json"
    d = json.loads(p.read_text())
    if not isinstance(d, dict) or d.get("schema") != "zrhfd-delivery-status-v1":
        raise ValueError("root DELIVERY_STATUS.json has invalid schema")
    if d.get("status") not in ("COMPLETE", "STOPPED") or d.get("decision_by") != "root" or d.get("measurement_closed") is not True:
        raise ValueError("delivery needs root COMPLETE/STOPPED written decision and measurement_closed=true")
    if not isinstance(d.get("written_conclusion"), str) or not d["written_conclusion"].strip():
        raise ValueError("root written_conclusion is required; FAIL is allowed")
    refs = d.get("conclusion_files")
    if not isinstance(refs, list) or not refs:
        raise ValueError("root conclusion_files must name existing written conclusion artifacts")
    for rel in refs:
        if not isinstance(rel, str) or not safe_member(rel) or not (Path(root) / rel).is_file() or (Path(root) / rel).is_symlink():
            raise ValueError(f"invalid root conclusion reference: {rel!r}")
    return {"decision": d, "status_sha256": sha_file(p),
            "conclusion_sha256": {rel: sha_file(Path(root) / rel) for rel in refs}}


def measurement_matches(command, root):
    try:
        args = shlex.split(command)
    except ValueError:
        return any(script in command for script in MEASUREMENT_SCRIPTS)
    for index, arg in enumerate(args):
        for script in MEASUREMENT_SCRIPTS:
            if arg == script or arg == str(Path(root) / script):
                return True
            if index and args[index - 1] == "-m" and arg == script[:-3].replace("/", "."):
                return True
        if arg.endswith("/native_driver.jl") or arg.endswith("/native_hyper_driver.jl") or arg.endswith("/mincut128"):
            return True
    return False


def live_measurements(root):
    output = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], check=True, capture_output=True, text=True).stdout
    rows = []
    for line in output.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3:
            continue
        pid, ppid, command = fields
        if int(pid) != os.getpid() and measurement_matches(command, root):
            rows.append({"pid": int(pid), "parent_pid": int(ppid), "command": command})
    return rows


def gate(root, status_sha=None, conclusions=None):
    state = validate_status(root)
    if status_sha and state["status_sha256"] != status_sha:
        raise ValueError("DELIVERY_STATUS.json changed while creating delivery")
    if conclusions is not None and state["conclusion_sha256"] != conclusions:
        raise ValueError("root written conclusion artifacts changed while creating delivery")
    live = live_measurements(root)
    if live:
        raise ValueError("live measurement process(es): " + json.dumps(live))
    return state


def zip_audit(stream, deny, depth=0, progress=None, raw_records=None):
    """Full CRC/read/SHA check of raw archive members; no extraction or mutation."""
    if depth > 8:
        raise ValueError("nested ZIP depth exceeds safe audit limit; originals retained")
    if raw_records is None:
        filename = stream if isinstance(stream, (str, Path)) else getattr(stream, "name", "")
        raw_records = PurePosixPath(str(filename)).name == "RAW_RECORDS.zip"
    records, children = [], {}
    with zipfile.ZipFile(stream) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(names) != len({n.casefold() for n in names}):
            raise ValueError("duplicate/case-colliding nested raw ZIP member")
        for info in infos:
            if not safe_member(info.filename):
                raise ValueError(f"unsafe nested ZIP member: {info.filename}")
            if info.is_dir():
                continue
            reason = exclusion(info.filename, scientific_partial=raw_records and partial_evidence_name(PurePosixPath(info.filename).name))
            if reason:
                raise ValueError(f"nested raw ZIP contains forbidden member {info.filename}: {reason}; original retained")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"nested raw ZIP symlink: {info.filename}")
            with z.open(info) as f:
                h, size = sha_stream(f, progress)
            if h in deny:
                raise ValueError(f"nested raw ZIP contains SHA-identical restricted author/paper file: {info.filename}")
            if size != info.file_size:
                raise ValueError(f"nested member size mismatch: {info.filename}")
            records.append({"path": info.filename, "size": size, "sha256": h, "crc32": info.CRC,
                            "compression_method": info.compress_type})
            if info.filename.lower().endswith(".zip"):
                with z.open(info) as f:
                    children[info.filename] = zip_audit(f, deny, depth + 1, progress,
                        raw_records=PurePosixPath(info.filename).name == "RAW_RECORDS.zip")
        # Apply the same sibling index rule inside every ZIP level, not just the outer filesystem.
        index_validation = audit_storage_indexes(records, children, z.read)
    return {"member_count": len(records), "members": records, "crc_and_sha_verified": True,
            "original_zip_bytes_preserved": True, "index_files_preserved_with_all_other_members": True,
            "nested_archives": children, "original_raw_index_validation": index_validation,
            "unpublished_partial_records": [x["path"] for x in records if partial_evidence_name(PurePosixPath(x["path"]).name)],
            "partial_records_completion_claim": False}


def audit_storage_indexes(entries, nested, read_bytes):
    """Validate existing archival.py index against byte-preserved ZIP members."""
    by_path = {entry["path"]: entry for entry in entries}
    validations = []
    for rel in sorted(by_path):
        if PurePosixPath(rel).name != "ARCHIVE.json":
            continue
        metadata = json.loads(read_bytes(rel))
        name = metadata.get("archive")
        if not isinstance(name, str) or not safe_member(name):
            raise ValueError(f"invalid original raw archive index: {rel}")
        archive_rel = (PurePosixPath(rel).parent / name).as_posix()
        if archive_rel not in by_path or archive_rel not in nested:
            raise ValueError(f"original archive/index pair missing: {rel}")
        if metadata.get("archive_sha256") != by_path[archive_rel]["sha256"]:
            raise ValueError(f"original archive file SHA/index mismatch: {rel}")
        files = metadata.get("files")
        actual = {x["path"]: x for x in nested[archive_rel]["members"]}
        if not isinstance(files, dict) or set(files) != set(actual):
            raise ValueError(f"original raw archive member set/index mismatch: {rel}")
        for member, record in files.items():
            if not isinstance(record, dict) or (record.get("sha256"), record.get("bytes")) != (actual[member]["sha256"], actual[member]["size"]):
                raise ValueError(f"original raw archive member SHA/index mismatch: {rel}:{member}")
            if "zip_compression_method" in record and record["zip_compression_method"] != actual[member]["compression_method"]:
                raise ValueError(f"original raw archive compression metadata/index mismatch: {rel}:{member}")
            expanded = (PurePosixPath(rel).parent / member).as_posix()
            if expanded in by_path and by_path[expanded]["sha256"] != record["sha256"]:
                raise ValueError(f"original expanded/archived copies disagree: {expanded}")
        partials = nested[archive_rel]["unpublished_partial_records"]
        if partials:
            terminal_status({"status": metadata.get("terminal_status")})
            receipt_candidates = [(PurePosixPath(rel).parent / name).as_posix() for name in ("receipt.json", "terminal.json")]
            receipt_rel = next((name for name in receipt_candidates if name in by_path), None)
            if receipt_rel is None:
                raise ValueError(f"indexed partial records lack original terminal receipt: {rel}")
            terminal = json.loads(read_bytes(receipt_rel))
            if terminal_status(terminal) != metadata.get("terminal_status"):
                raise ValueError(f"indexed partial receipt/status mismatch: {rel}")
            if metadata.get("terminal_receipt_sha256", by_path[receipt_rel]["sha256"]) != by_path[receipt_rel]["sha256"]:
                raise ValueError(f"indexed partial terminal receipt SHA mismatch: {rel}")
        validations.append({"index": rel, "archive": archive_rel, "member_count": len(actual),
                            "original_index_member_sha_verified": True})
    paired = {x["archive"] for x in validations}
    if any(PurePosixPath(rel).name == "RAW_RECORDS.zip" and rel not in paired for rel in nested):
        raise ValueError("RAW_RECORDS.zip missing its original ARCHIVE.json index")
    return validations


def same_stat(path, expected):
    return stat_record(path, expected["path"]) == expected and not path.is_symlink()


def zip_info(rel, mode):
    info = zipfile.ZipInfo(rel, (1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = zipfile.ZIP_STORED if rel.lower().endswith((".zip", ".png", ".pdf", ".jpg", ".gz")) else zipfile.ZIP_DEFLATED
    return info


def create_zip(root, inv, temporary, state, *, check_gate=True):
    """Internal function permits tiny fixture projects; CLI never bypasses gate."""
    root = Path(root)
    deny = author_denied(root)
    entries, nested, content_excluded, omitted_hashes = [], {}, [], []
    last_gate = time.monotonic()
    def check_control():
        nonlocal last_gate
        if check_gate and time.monotonic() - last_gate > 5:
            gate(root, state["status_sha256"], state["conclusion_sha256"])
            last_gate = time.monotonic()
    with zipfile.ZipFile(temporary, "x", allowZip64=True, compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for original in inv["included"]:
            path = root / original["path"]
            if not same_stat(path, original):
                raise ValueError(f"file changed after inventory: {original['path']}")
            scientific_partial_receipt(path, root, validate=True)
            # First stream pass catches renamed third-party copies before ZIP publication.
            h = sha_file(path, check_control)
            if h in deny:
                content_excluded.append({**original, "sha256": h, "reason": "SHA-identical restricted author/paper original", "source_receipts": deny[h]})
                continue
            if path.suffix.lower() == ".zip":
                nested[original["path"]] = zip_audit(path, deny, progress=check_control)
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as source, z.open(zip_info(original["path"], original["mode"]), "w", force_zip64=True) as target:
                while True:
                    data = source.read(CHUNK)
                    if not data:
                        break
                    target.write(data)
                    digest.update(data)
                    size += len(data)
                    check_control()
            if digest.hexdigest() != h or size != original["size"] or not same_stat(path, original):
                raise ValueError(f"file changed during packaging: {original['path']}")
            entries.append({**original, "sha256": h})
        # Omitted generated inputs receive actual streamed SHA, distinct from metadata-only inventory.
        for original in inv["excluded"]:
            if original.get("size") is None or not original["path"].startswith("data/"):
                continue
            path = root / original["path"]
            if not same_stat(path, {k: original[k] for k in ("path", "size", "mtime_ns", "mode", "inode", "device")}):
                raise ValueError(f"omitted input changed: {original['path']}")
            omitted_sha = sha_file(path, check_control)
            if not same_stat(path, {k: original[k] for k in ("path", "size", "mtime_ns", "mode", "inode", "device")}):
                raise ValueError(f"omitted input changed during hashing: {original['path']}")
            omitted_hashes.append({"path": original["path"], "size": original["size"], "sha256": omitted_sha, "reason": original["reason"]})
        index_validation = audit_storage_indexes(entries, nested, lambda rel: (root / rel).read_bytes())
        manifest = {**inv, "operation": "verified_private_delivery", "created_utc": utc(),
                    "raw_file_hashing_performed": True, "zip_opened": True, "included": entries,
                    "included_count": len(entries), "included_logical_bytes": sum(x["size"] for x in entries),
                    "content_excluded": content_excluded, "omitted_input_stream_sha256": omitted_hashes,
                    "nested_raw_archives": nested, "original_raw_index_validation": index_validation, "root_delivery_decision": state,
                    "actual_command": sys.argv, "tool_sha256": sha_file(Path(__file__)),
                    "python_version": sys.version, "manifest_self_sha_policy": "manifest SHA recorded in external receipt; no recursive self-hash"}
        z.writestr(zip_info(MANIFEST, 0o644), encode(manifest))
    return manifest


def verify_zip(path, progress=None):
    """Verify every payload SHA and all nested raw member SHA/CRC against manifest."""
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(names) != len({n.casefold() for n in names}) or any(not safe_member(n) for n in names):
            raise ValueError("unsafe/duplicate delivery ZIP member")
        raw = z.read(MANIFEST)
        m = json.loads(raw)
        if m.get("schema") != SCHEMA or m.get("operation") != "verified_private_delivery":
            raise ValueError("invalid delivery manifest")
        entries = m["included"]
        expected = {x["path"] for x in entries} | {MANIFEST}
        if len(entries) != len(expected) - 1 or set(names) != expected:
            raise ValueError("delivery member set disagrees with manifest")
        for entry in entries:
            with z.open(entry["path"]) as f:
                h, size = sha_stream(f, progress)
            if (h, size) != (entry["sha256"], entry["size"]):
                raise ValueError(f"payload SHA/size mismatch: {entry['path']}")
            if entry["path"] in m["nested_raw_archives"]:
                with z.open(entry["path"]) as f:
                    actual = zip_audit(f, {}, progress=progress)
                if actual != m["nested_raw_archives"][entry["path"]]:
                    raise ValueError(f"nested raw archive manifest mismatch: {entry['path']}")
        if audit_storage_indexes(entries, m["nested_raw_archives"], z.read) != m["original_raw_index_validation"]:
            raise ValueError("raw archive index validation disagrees with delivery manifest")
    return {"schema": SCHEMA, "verified_utc": utc(), "verified": True,
            "payload_count": len(entries), "nested_raw_archive_count": len(m["nested_raw_archives"]),
            "manifest_sha256": hashlib.sha256(raw).hexdigest(), "zip_sha256": sha_file(path, progress),
            "zip_bytes": Path(path).stat().st_size, "cryptographic_authenticity": "integrity against included manifest; receipt pins trusted delivery bytes"}


def download_link(canonical, downloads):
    canonical, downloads = Path(canonical), Path(downloads)
    if not downloads.is_dir():
        raise ValueError("Downloads destination must already be a directory")
    if canonical.stat().st_dev != downloads.stat().st_dev:
        return {"status": "NOT_LINKED_DIFFERENT_VOLUME", "canonical_retained": True}
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = downloads / ("ZR-HFD_DELIVERY_" + timestamp + ".zip")
    os.link(canonical, target)  # exclusive, never replaces a user file
    return {"status": "HARDLINK_CREATED", "path": str(target), "same_inode": target.stat().st_ino == canonical.stat().st_ino}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--create", action="store_true", help="requires root delivery conclusion and no live measurements")
    group.add_argument("--verify", type=Path, help="stream verify an already created delivery")
    parser.add_argument("--inventory-output", type=Path, help="exclusive metadata-only JSON output")
    parser.add_argument("--downloads", type=Path, help="after creation, exclusive same-volume timestamp hardlink")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.verify:
        if args.downloads or args.inventory_output:
            parser.error("--verify cannot publish inventory or Downloads link")
        print(json.dumps(verify_zip(args.verify), indent=2))
        return
    if not args.create:
        if args.downloads:
            parser.error("--downloads requires --create")
        inv = inventory(root)
        if args.inventory_output:
            immutable_json(args.inventory_output, inv)
        print(json.dumps({k: inv[k] for k in ("operation", "included_count", "included_logical_bytes", "raw_file_hashing_performed", "zip_opened")}))
        return
    state = gate(root)
    canonical = root / "DELIVERY.zip"
    if canonical.exists() or canonical.is_symlink():
        raise FileExistsError("canonical DELIVERY.zip already exists; verify it, never overwrite")
    inv = inventory(root)
    receipt_dir = root / "reviews/delivery" / ("creation_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    receipt_dir.mkdir(parents=True, exist_ok=False)
    # Receipt is outside payload inventory; capture exactly what was about to happen.
    immutable_json(receipt_dir / "request.json", {"actual_command": sys.argv, "root_delivery_decision": state,
                   "inventory_count": inv["included_count"], "tool_sha256": sha_file(Path(__file__)), "created_utc": utc()})
    temporary = root / (".DELIVERY.zip.partial-" + uuid.uuid4().hex)
    started = time.monotonic()
    canonical_published = False
    try:
        manifest = create_zip(root, inv, temporary, state)
        with temporary.open("rb") as f:
            os.fsync(f.fileno())
        verified_last_gate = time.monotonic()
        def verify_control():
            nonlocal verified_last_gate
            if time.monotonic() - verified_last_gate > 5:
                gate(root, state["status_sha256"], state["conclusion_sha256"])
                verified_last_gate = time.monotonic()
        checked = verify_zip(temporary, verify_control)
        gate(root, state["status_sha256"], state["conclusion_sha256"])
        # Detect late-added result/source files too. Metadata dates may evolve only by failure -> abort.
        final = inventory(root)
        current = [x for x in final["included"] if not x["path"].startswith(receipt_dir.relative_to(root).as_posix() + "/")]
        if current != inv["included"] or final["excluded"] != inv["excluded"]:
            raise ValueError("project inventory changed during packaging; preserved partial ZIP")
        os.link(temporary, canonical)  # exclusive atomic canonical publication, never clobber
        canonical_published = True
        temporary.unlink()
        receipt = {**checked, "status": "CREATED_VERIFIED", "canonical": "DELIVERY.zip", "wall_seconds": time.monotonic() - started}
        if args.downloads:
            try:
                receipt["downloads"] = download_link(canonical, args.downloads)
            except OSError as exc:
                receipt["downloads"] = {"status": "LINK_FAILED_CANONICAL_VERIFIED_RETAINED", "error": str(exc), "type": type(exc).__name__}
        immutable_json(receipt_dir / "receipt.json", receipt)
        immutable_json(receipt_dir / "manifest.json", manifest)
        print(json.dumps(receipt, indent=2))
    except BaseException as exc:
        immutable_json(receipt_dir / "failure.json", {"status": "CREATE_FAILED_OR_INTERRUPTED", "type": type(exc).__name__,
                       "error": str(exc), "temporary_zip_preserved": str(temporary) if temporary.exists() else None,
                       "canonical_verified_published": canonical_published,
                       "original_raw_modified": False, "wall_seconds": time.monotonic() - started})
        raise


if __name__ == "__main__":
    main()
