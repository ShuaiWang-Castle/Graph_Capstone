#!/usr/bin/env python3
"""Acquire pinned public baseline sources without installing dependencies."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "provenance/baselines/acquisition.json"
PAPERS = {
    "hfd": ("2102.07945v4", "Local Hyper-Flow Diffusion"),
    "tlhfd": ("2606.09340v1", "Thresholded Local Hyper-Flow Diffusion"),
    "cfsp": ("1306.3409v1", "Constrained fractional set programs and their application in local clustering and community detection"),
    "pnorm": ("2005.09810v3", "p-Norm Flow Diffusion for Local Graph Clustering"),
}
REPOS = {
    "hfd": ("https://github.com/s-h-yang/HFD.git", None),
    "localgraphclustering": ("https://github.com/kfoynt/LocalGraphClustering.git", ["localgraphclustering"]),
    "leidenalg": ("https://github.com/vtraag/leidenalg.git", None),
    "pnormflowdiffusion": ("https://github.com/s-h-yang/pNormFlowDiffusion.git", ["reproducibility"]),
}


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(record):
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    temp = RECORD.with_suffix(".json.tmp")
    temp.write_text(json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(RECORD)


def run(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--papers-only", action="store_true")
    parser.add_argument("--repos-only", action="store_true")
    args = parser.parse_args()
    record = json.loads(RECORD.read_text()) if RECORD.exists() else {"papers": {}, "repositories": {}, "failures": []}
    if not args.repos_only:
        for name, (arxiv, title) in PAPERS.items():
            target = ROOT / "external/papers" / (name + ".pdf")
            if name in record["papers"] and target.exists():
                if digest(target) != record["papers"][name]["sha256"]:
                    raise RuntimeError("Retained paper checksum changed: " + name)
                continue
            url = "https://arxiv.org/pdf/" + arxiv
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(url, timeout=90) as response:
                    raw = response.read()
                    final_url = response.geturl()
                if not raw.startswith(b"%PDF-"):
                    raise ValueError("Response is not a PDF")
                temp = target.with_suffix(".pdf.tmp")
                temp.write_bytes(raw)
                temp.replace(target)
                record["papers"][name] = {"title": title, "arxiv_version": arxiv, "url": url, "final_url": final_url, "retrieved_at": utc(), "path": str(target.relative_to(ROOT)), "bytes": len(raw), "sha256": digest(target)}
                save(record)
                print("paper acquired:", name, len(raw), flush=True)
            except Exception as exc:
                record["failures"].append({"item": name, "url": url, "at": utc(), "error": repr(exc)})
                save(record)
                print("paper acquisition failed:", name, repr(exc), flush=True)
    if not args.papers_only:
        for name, (url, sparse_paths) in REPOS.items():
            target = ROOT / "external" / name
            try:
                if not target.exists():
                    command = ["git", "clone", "--depth", "1"]
                    if sparse_paths:
                        command += ["--filter=blob:none", "--sparse"]
                    run(command + [url, str(target)])
                    if sparse_paths:
                        run(["git", "-C", str(target), "sparse-checkout", "set"] + sparse_paths)
                commit = run(["git", "-C", str(target), "rev-parse", "HEAD"])
                if name in record["repositories"] and record["repositories"][name]["commit"] != commit:
                    raise RuntimeError("Retained source pin changed: " + name)
                licenses = sorted(p for p in target.rglob("*") if p.is_file() and not ".git" in p.parts and (p.name.lower().startswith("license") or p.name.lower().startswith("copying")))
                tracked = run(["git", "-C", str(target), "ls-files"]).splitlines()
                file_hashes = {p: digest(target / p) for p in tracked if (target / p).is_file()}
                previous = record["repositories"].get(name, {})
                record["repositories"][name] = {"url": url, "commit": commit, "retrieved_at": previous.get("retrieved_at", utc()), "path": str(target.relative_to(ROOT)), "sparse_checkout_paths": sparse_paths, "tracked_worktree_file_sha256": file_hashes, "license_files": [{"path": str(p.relative_to(ROOT)), "sha256": digest(p)} for p in licenses], "license_status": "license files preserved; inspect exact terms" if licenses else "No license file located in this acquired source; redistribution permission unverified"}
                save(record)
                print("repository pinned:", name, commit, "files", len(file_hashes), flush=True)
            except Exception as exc:
                record["failures"].append({"item": name, "url": url, "at": utc(), "error": repr(exc)})
                save(record)
                print("repository acquisition failed:", name, repr(exc), flush=True)


if __name__ == "__main__":
    main()
