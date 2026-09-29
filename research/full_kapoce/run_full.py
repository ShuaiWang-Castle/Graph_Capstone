"""Preview-only import shim for the omitted full KaPoCE adapter.

The original adapter and upstream native implementation are outside this
curated Python preview. This function never simulates full-solver results.
"""


def run_full_case(*args, **kwargs):
    raise RuntimeError(
        "Full KaPoCE execution is unavailable in the public Python preview; "
        "obtain the upstream GPLv3 implementation and the separate adapter "
        "from the primary research archive before reproducing native runs."
    )
