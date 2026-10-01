"""Topology-only undirected graph input and exact integer objective arithmetic."""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import json
import numpy as np
from scipy import sparse


@dataclass
class Graph:
    n: int
    edges: list
    indptr: np.ndarray
    indices: np.ndarray
    weights: np.ndarray
    degree: np.ndarray
    total: float
    integer_weights: bool

    @classmethod
    def from_edges(cls, n, edges):
        rows, cols, values, normalized = [], [], [], []
        for edge in edges:
            u, v = int(edge[0]), int(edge[1])
            w = float(edge[2]) if len(edge) == 3 else 1.0
            if not (0 <= u < n and 0 <= v < n) or u == v or w <= 0:
                raise ValueError('Require positive loopless undirected edges')
            normalized.append((u, v, w))
            rows.extend((u, v)); cols.extend((v, u)); values.extend((w, w))
        A = sparse.coo_matrix((values, (rows, cols)), shape=(n, n)).tocsr()
        A.sum_duplicates(); A.sort_indices()
        # Parallel entries are combined once, so all downstream edge data and
        # degree agree with the sparse adjacency.
        upper = sparse.triu(A, 1).tocoo()
        normalized = list(zip(upper.row.tolist(), upper.col.tolist(), upper.data.tolist()))
        d = np.asarray(A.sum(axis=1)).ravel()
        return cls(int(n), normalized, A.indptr.astype(np.int64),
                   A.indices.astype(np.int64), A.data.astype(np.float64),
                   d, float(d.sum()), bool(np.all(A.data == np.rint(A.data))))

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return cls.from_edges(data['n'], data['edges'])

    def adjacency(self):
        return sparse.csr_matrix((self.weights, self.indices, self.indptr), shape=(self.n, self.n))

    def stats(self, vertices):
        vertices = set(map(int,vertices))
        volume = float(self.degree[list(vertices)].sum())
        cut = 0.0
        for u in vertices:
            for j in range(self.indptr[u],self.indptr[u+1]):
                if int(self.indices[j]) not in vertices:cut += self.weights[j]
        if self.integer_weights:
            volume, cut, total = int(round(volume)), int(round(cut)), int(round(self.total))
            z = Fraction(cut * total + volume * volume, total * volume) if volume else None
        else:
            total = self.total
            z = cut / volume + volume / total if volume else None
        denom = min(volume, total-volume)
        return {'volume':volume,'cut':cut,'Z':float(z) if z is not None else None,
                'Z_exact':str(z) if z is not None and self.integer_weights else None,
                'phi':cut/denom if denom > 0 else None,
                'phi_v':cut/volume if volume else None,'size':len(vertices)}

    def z_exact(self, vertices):
        if not self.integer_weights:
            raise ValueError('Exact main-method refinement requires integer-weight graph')
        stat = self.stats(vertices)
        if stat['Z_exact'] is None:
            raise ValueError('Zero-volume set has undefined Z')
        return Fraction(stat['Z_exact'])

    def components(self, vertices):
        todo = set(map(int, vertices)); sizes = []
        while todo:
            start = todo.pop(); stack = [start]; size = 0
            while stack:
                u = stack.pop(); size += 1
                for v in self.indices[self.indptr[u]:self.indptr[u+1]]:
                    v = int(v)
                    if v in todo: todo.remove(v); stack.append(v)
            sizes.append(size)
        return sizes
