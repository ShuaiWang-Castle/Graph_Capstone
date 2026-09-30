"""CPU functional prototype: an existing sampled_addmm primitive, not a new loss.

Index preparation is explicit and must be charged to any later measured run.
No labels, graph generator, benchmarking, decoder rules or training loop here.
"""
from dataclasses import dataclass
import numpy as np
import torch


@dataclass
class PreparedPairs:
    n: int
    pairs: np.ndarray
    unique_pairs: np.ndarray
    inverse: torch.Tensor
    crow: torch.Tensor
    col: torch.Tensor

    def mask(self, dtype):
        return torch.sparse_csr_tensor(
            self.crow, self.col, torch.ones(len(self.unique_pairs), dtype=dtype),
            size=(self.n, self.n), device='cpu', check_invariants=True)


def prepare_pairs(pairs, n):
    if isinstance(pairs, torch.Tensor):
        if pairs.device.type != 'cpu':
            raise ValueError('This prototype is CPU-only')
        pairs = pairs.detach().numpy()
    pairs = np.asarray(pairs)
    if pairs.ndim != 2 or pairs.shape[1] != 2:
        raise ValueError('Pairs must have shape [batch,2]')
    if not np.issubdtype(pairs.dtype, np.integer):
        raise TypeError('Pairs must be integers')
    if not len(pairs):
        raise ValueError('Empty pair batches deliberately unsupported; BerPo means are undefined')
    if n < 1 or pairs.min() < 0 or pairs.max() >= n:
        raise ValueError('Pair outside node universe')
    pairs = np.asarray(pairs, dtype=np.int64).copy()
    if n*n > np.iinfo(np.int64).max:
        raise ValueError('Linear pair IDs would overflow int64')
    keys = pairs[:, 0]*n + pairs[:, 1]
    unique_keys, inverse = np.unique(keys, return_inverse=True)
    unique = np.column_stack((unique_keys//n, unique_keys%n))
    counts = np.bincount(unique[:, 0], minlength=n)
    crow = np.r_[0, np.cumsum(counts)].astype(np.int64)
    # np.unique(axis=0) is row/column lexicographic: this is exact CSR values order.
    return PreparedPairs(n, pairs, unique, torch.from_numpy(inverse.astype(np.int64)),
                         torch.from_numpy(crow), torch.from_numpy(unique[:, 1].copy()))


def sparse_pair_dot(emb, prepared):
    if emb.device.type != 'cpu' or emb.dtype not in (torch.float32, torch.float64):
        raise TypeError('Only CPU float32/float64 verified by this prototype')
    if emb.ndim != 2 or emb.shape[0] != prepared.n:
        raise ValueError('Embedding node universe mismatch')
    sampled = torch.sparse.sampled_addmm(prepared.mask(emb.dtype), emb, emb.t(),
                                        beta=0, alpha=1)
    # The inverse gather is differentiable and restores duplicate multiplicity
    # and the complete original ordered batch. Both F and F.T remain connected.
    return sampled.values()[prepared.inverse]


def elementwise_pair_dot(emb, pairs):
    return (emb[pairs[:, 0]] * emb[pairs[:, 1]]).sum(dim=1)


def bmm_pair_dot(emb, pairs):
    lhs = emb[pairs[:, 0]].unsqueeze(1)
    rhs = emb[pairs[:, 1]].unsqueeze(2)
    return torch.bmm(lhs, rhs).reshape(-1)


def batch_loss_with_pair_dot(decoder, emb, ones, zeros, dot):
    edge_dots = dot(emb, ones)
    loss_edges = -torch.mean(torch.log(-torch.expm1(-decoder.eps-edge_dots)))
    loss_nonedges = torch.mean(dot(emb, zeros))
    neg_scale = 1.0 if decoder.balance_loss else decoder.num_nonedges/decoder.num_edges
    return (loss_edges+neg_scale*loss_nonedges)/(1+neg_scale)


def full_loss_with_pair_dot(decoder, emb, adj, dot):
    rows, cols = adj.nonzero()
    pairs = torch.from_numpy(np.column_stack((rows, cols)).astype(np.int64))
    edge_dots = dot(emb, pairs)
    loss_edges = -torch.sum(torch.log(-torch.expm1(-decoder.eps-edge_dots)))
    correction = torch.sum(emb*emb)+torch.sum(edge_dots)
    sum_emb = torch.sum(emb, dim=0, keepdim=True).t()
    loss_nonedges = torch.sum(emb@sum_emb)-correction
    neg_scale = 1.0 if decoder.balance_loss else decoder.num_nonedges/decoder.num_edges
    return (loss_edges/decoder.num_edges+neg_scale*loss_nonedges/decoder.num_nonedges)/(1+neg_scale)
