"""Preview-only import shim for the omitted native KaPoCE adapter.

The original adapter and upstream native implementation are outside this
curated Python preview. This function never simulates native results.
"""


def run_case(*args, **kwargs):
    raise RuntimeError(
        "Native KaPoCE execution is unavailable in the public Python preview; "
        "obtain the upstream GPLv3 implementation and the separate adapter "
        "from the primary research archive before reproducing native runs."
    )
