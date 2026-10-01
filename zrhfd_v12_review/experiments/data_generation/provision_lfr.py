"""Copy read-only native LFR source/binary and retain license/hash provenance."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument("--source",required=True);a=p.parse_args()
    source=Path(a.source).resolve();dest=ROOT/"external/generators/lfr_native"
    if dest.exists():raise RuntimeError("Generator copy already exists; refuse mutation")
    dest.mkdir(parents=True)
    for name in ["LICENSE","unweighted_undirected"]:
        src=source/name;dst=dest/name
        if src.is_dir():shutil.copytree(src,dst,ignore=shutil.ignore_patterns("__pycache__","*.o"))
        else:shutil.copy2(src,dst)
    commit=subprocess.check_output(["git","-C",str(source),"rev-parse","HEAD"],text=True).strip()
    origin=subprocess.check_output(["git","-C",str(source),"remote","get-url","origin"],text=True).strip()
    records={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(dest.rglob("*")) if p.is_file()}
    out=ROOT/"provenance/generators";out.mkdir(parents=True,exist_ok=True)
    (out/"lfr_native.json").write_text(json.dumps({"upstream_url":origin,"upstream_commit":commit,"copied_at_utc":datetime.now(timezone.utc).isoformat(),
          "license":"MIT; preserved verbatim","source_origin":"Read-only local existing checkout; no upstream modifications",
          "binary_status":"Copied existing native CPU binary; its bytes pinned below", "files_sha256":records},indent=1))
    print(json.dumps({"commit":commit,"copied_files":len(records),"binary_sha256":sha(dest/"unweighted_undirected/benchmark")}))
if __name__=="__main__":main()
