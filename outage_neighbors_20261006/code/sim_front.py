"""A small model: a storm front crosses a set of counties; does the Fiedler vector of the outage-similarity graph
recover the order of arrival?

Each county's outage share rises quickly when the front arrives and decays exponentially with its own time constant.
Counties are compared by the correlation of their hourly curves; no positions or arrival times enter the graph.
This only shows that the method works when curves are shifted copies of one shape. It is not evidence about real storms.
"""
import networkx as nx
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import eigsh
from scipy.stats import spearmanr
from sklearn.neighbors import NearestNeighbors

rng = np.random.default_rng(1)


def simulate(n=300, hours=216, noise=0.05, two_waves=True):
    x, y = rng.uniform(0, 600, n), rng.uniform(0, 300, n)
    t = np.arange(hours)[None, :]

    def wave(arrival, amp, tau):
        s = np.clip(t - arrival[:, None], 0, None)
        return amp[:, None] * (1 - np.exp(-s / 2.0)) * np.exp(-s / tau[:, None])

    a1 = 40 + x / 12 + rng.normal(0, 1.5, n)                      # west-to-east front
    u = wave(a1, rng.lognormal(-1.5, 0.6, n), rng.uniform(6, 30, n))
    hit = np.zeros(n, bool)
    if two_waves:                                                  # a second storm reaches the south-east later
        hit = (x > 300) & (y < 180)
        a2 = np.where(hit, 120 + (300 - y) / 15 + rng.normal(0, 1.5, n), 0.0)
        u = u + np.where(hit[:, None], wave(a2, rng.lognormal(-1.2, 0.5, n), rng.uniform(10, 40, n)), 0)
    return x, a1, hit, u + noise * rng.standard_normal(u.shape) * u.max()


def fiedler(u, k=10, nvec=3):
    z = (u - u.mean(1, keepdims=True)) / (u.std(1, keepdims=True) + 1e-12)
    idx = NearestNeighbors(n_neighbors=k + 1, metric="correlation", algorithm="brute").fit(z).kneighbors(z)[1][:, 1:]
    n = len(u)
    a = sp.csr_matrix((np.ones(idx.size), (np.repeat(np.arange(n), k), idx.ravel())), shape=(n, n))
    a = ((a + a.T) > 0).astype(float)
    d = np.asarray(a.sum(1)).ravel()
    dm = sp.diags(d ** -0.5)
    w, v = eigsh(sp.identity(n) - dm @ a @ dm, k=nvec + 1, sigma=-1e-3, which="LM")
    o = np.argsort(w)
    return w[o], dm @ v[:, o], a


if __name__ == "__main__":
    for noise in (0.02, 0.05, 0.15):
        for two in (False, True):
            x, a1, hit, u = simulate(noise=noise, two_waves=two)
            w, v, a = fiedler(u)
            line = (f"noise {noise:4.2f}, {'two waves' if two else 'one wave '}: components "
                    f"{nx.number_connected_components(nx.from_scipy_sparse_array(a))}, |Spearman| of the Fiedler vector with the "
                    f"arrival time {abs(spearmanr(v[:, 1], a1).statistic):.3f}, with longitude {abs(spearmanr(v[:, 1], x).statistic):.3f}")
            if two:
                best = max(abs(spearmanr(v[:, j], hit.astype(float)).statistic) for j in (1, 2, 3))
                line += f"; best of the first three eigenvectors against 'hit by the second wave' {best:.3f}"
            print(line)
