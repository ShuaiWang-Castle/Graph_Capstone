"""Hash/version gate for one prospective source/configuration version."""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[3]
NAMESPACE = Path("experiments/extensions/metric_sdp")
RUNTIME = (
    "src/degree_contraction/__init__.py",
    "src/degree_contraction/certificate.py",
    "src/degree_contraction/quotient.py",
    "experiments/candidates.py",
    "experiments/datasets.py",
    "experiments/families.py",
    "experiments/pipeline.py",
    "experiments/extensions/__init__.py",
    "research/baselines/weighted_reference.py",
    *(str(NAMESPACE / x) for x in
      ("__init__.py", "rational.py", "safe_composition.py", "numerical.py",
       "runtime.py", "freeze.py", "run_case.py", "run_pilot.py")),
)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_once(path, value):
    """Exclusive atomic JSON; a watchdog never observes a half-written marker."""
    path = Path(path)
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("x") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.link(temporary, path)
    temporary.unlink()


def runtime_sources():
    return {p: sha256(ROOT / p) for p in RUNTIME}


def environment():
    import cvxpy, scs
    from cvxpy.reductions.solvers.conic_solvers import scs_conif
    from cvxpy.problems import problem
    import scs._scs_direct as direct
    import scs._scs_indirect as indirect
    libraries = {"cvxpy.problem": problem.__file__,
                 "cvxpy.scs_conif": scs_conif.__file__,
                 "scs.python": scs.__file__,
                 "scs.direct": direct.__file__,
                 "scs.indirect": indirect.__file__}
    return {"python": platform.python_version(),
            "platform": platform.platform(), "machine": platform.machine(),
            "versions": {name: importlib.metadata.version(name) for name in
                         ("cvxpy", "scs", "numpy", "scipy", "networkx", "psutil")},
            "installed_packages": dict(sorted(
                (dist.metadata["Name"].lower(), dist.version)
                for dist in importlib.metadata.distributions())),
            "inspected_library_sha256": {name: sha256(path)
                                        for name, path in libraries.items()}}


def validate_import_origins(source_map):
    """The actual loaded code must come from the pinned workspace sources."""
    for path, digest in source_map.items():
        parts = list(Path(path).parts)
        if parts[0] == "src":
            parts.pop(0)
        name = Path(parts[-1]).stem
        parts = parts[:-1] + ([] if name == "__init__" else [name])
        module = importlib.import_module(".".join(parts))
        origin = Path(module.__file__).resolve()
        expected = (ROOT / path).resolve()
        if origin != expected or sha256(origin) != digest:
            raise ValueError("actual imported source differs from freeze: " + path)


def validate(config_path, freeze_path):
    config_path, freeze_path = Path(config_path), Path(freeze_path)
    config = json.loads(config_path.read_text())
    frozen = json.loads(freeze_path.read_text())
    if frozen["status"] != "frozen_for_six_bounded_U_only_pilot_jobs":
        raise ValueError("this source version has no pilot execution approval")
    if frozen["config_sha256"] != sha256(config_path):
        raise ValueError("prospective config changed after freeze")
    if frozen["runtime_source_sha256"] != runtime_sources():
        raise ValueError("transitive runtime source changed after freeze")
    validate_import_origins(frozen["runtime_source_sha256"])
    if frozen["environment"] != environment():
        raise ValueError("runtime/library version or inspected source changed")
    for path, digest in frozen["required_artifact_sha256"].items():
        if sha256(ROOT / path) != digest:
            raise ValueError("required protocol/review/test evidence changed: " + path)
    if any(os.getenv(k) != v for k, v in config["threads"].items()):
        raise ValueError("frozen single-thread environment required before imports")
    if config["solver"]["backend"] is not None:
        raise ValueError("pilot source cannot silently choose the formal backend")
    return config, frozen
