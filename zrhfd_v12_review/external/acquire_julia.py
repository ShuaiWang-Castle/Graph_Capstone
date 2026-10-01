#!/usr/bin/env python3
"""Download an official pinned Julia runtime into this project, never globally."""
from pathlib import Path
import datetime
import hashlib
import json
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
URL = "https://julialang-s3.julialang.org/bin/mac/aarch64/1.10/julia-1.10.10-macaarch64.tar.gz"
EXPECTED = "52d3f82c50d9402e42298b52edc3d36e0f73e59f81fc8609d22fa094fbad18be"
DEST = ROOT / "external/runtime"
DEST.mkdir(parents=True, exist_ok=True)
archive = DEST / "julia-1.10.10-macaarch64.tar.gz"
if not archive.exists():
    temp = archive.with_suffix(".gz.tmp")
    with urllib.request.urlopen(URL, timeout=120) as response, temp.open("wb") as out:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            out.write(block)
    temp.replace(archive)
hasher = hashlib.sha256()
with archive.open("rb") as source:
    while True:
        block = source.read(1024 * 1024)
        if not block:
            break
        hasher.update(block)
if hasher.hexdigest() != EXPECTED:
    raise RuntimeError("Official Julia checksum mismatch")
with tarfile.open(archive) as pack:
    for member in pack.getmembers():
        path = (DEST / member.name).resolve()
        if DEST.resolve() not in path.parents and path != DEST.resolve():
            raise RuntimeError("Unsafe archive path")
        if member.islnk() or member.issym():
            linked = ((path.parent / member.linkname) if member.issym() else (DEST / member.linkname)).resolve()
            if DEST.resolve() not in linked.parents:
                raise RuntimeError("Archive link escapes task runtime")
    pack.extractall(DEST)
binaries = sorted(DEST.rglob("bin/julia"))
licenses = sorted(p for p in DEST.rglob("LICENSE*" ) if p.is_file())
record = {"version": "1.10.10", "url": URL, "sha256": EXPECTED, "official_checksum_source": "https://julialang.org/downloads/oldreleases/", "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "archive_path": str(archive.relative_to(ROOT)), "binary_paths": [str(p.relative_to(ROOT)) for p in binaries], "license_paths": [str(p.relative_to(ROOT)) for p in licenses]}
target = ROOT / "provenance/baselines/julia-runtime.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print(json.dumps(record))
