"""Provisional degree-weighted block contraction with exact acceptance checks."""

from .certificate import (
    BlockCertificate,
    ExteriorDeviation,
    PreparedGraph,
    certify_block,
    prepare_graph,
    sparse_exterior_deviation,
)
from .quotient import (
    QuotientGraph,
    contract_certified_blocks,
    lift_labels,
    modularity,
    modularity_exact,
    quotient_adjacency,
)

__all__ = [
    "BlockCertificate", "ExteriorDeviation", "PreparedGraph", "QuotientGraph",
    "certify_block", "contract_certified_blocks", "lift_labels", "modularity",
    "modularity_exact", "prepare_graph", "quotient_adjacency",
    "sparse_exterior_deviation",
]
