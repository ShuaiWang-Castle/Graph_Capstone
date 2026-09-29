"""Rerun the entire failed case with only a reviewed fail-stop exception."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments import run_controls
from experiments.run_public import sha256, write_once
from experiments.recovery.policy import recovery_preserver, validate_recovery


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--stratum", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--recovery-freeze", required=True)
    args = parser.parse_args()
    recovery, _ = validate_recovery(args.recovery_freeze)
    if (args.config, args.freeze, args.stratum, args.case) != (
        recovery["original_config_path"], recovery["original_freeze_path"], "development", "davis"
    ):
        raise ValueError("Recovery case/configuration differ from reviewed plan")
    if (args.run_dir != recovery["planned_recovery_run_dir"]
            or Path(args.run_dir).resolve() == Path(recovery["parent_run_dir"]).resolve()):
        raise ValueError("Recovery case output differs from fixed prospective selection")
    manifest = json.loads((Path(args.run_dir) / "run-manifest.json").read_text())
    if (manifest.get("recovery_freeze_sha256") != sha256(args.recovery_freeze)
            or manifest.get("status") != "launched_recovery"):
        raise ValueError("Recovery case requires the reviewed recovery controller manifest")
    with open(args.config) as stream:
        config = json.load(stream)
    write_once(f"{args.run_dir}/development-davis-recovery-provenance.json", {
        "case": "development-davis", "overlay_applied": True,
        "config_sha256": sha256(args.config), "base_freeze_sha256": sha256(args.freeze),
        "recovery_freeze_sha256": sha256(args.recovery_freeze),
        "overlay_runtime_source_sha256": recovery["overlay_runtime_source_sha256"],
        "review_sha256": recovery["review_sha256"],
        "scope": "only exact paired failure-preservation halt exception; all algorithms, configuration and solver status unchanged",
    })
    run_controls.preserve_native_failure = recovery_preserver(
        run_controls.preserve_native_failure, sha256(args.recovery_freeze))
    run_controls.run_case(args.stratum, args.case, config, args.run_dir, args.config, args.freeze)


if __name__ == "__main__":
    main()
