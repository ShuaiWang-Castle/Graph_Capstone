import sknetwork as sn
import numpy as np
import scipy.sparse as sp
import numba
from numba.typed import List
from numba.types import int32
from tqdm import tqdm


class ConnectedComponents(sn.clustering.BaseClustering):
    """
    A helper class that allows connected components to behave like a clustering algorithm.
    The clusters are the connected components of the input graph
    """

    def __init__(
        self,
        sort_clusters: bool = True,
        return_probs: bool = False,
        return_aggregate: bool = False,
    ):
        super(ConnectedComponents, self).__init__(
            sort_clusters=sort_clusters,
            return_probs=return_probs,
            return_aggregate=return_aggregate,
        )

    def fit(self, g):
        self.labels_ = sp.csgraph.connected_components(g)[1]
        return self


#################################
# Helper Functions for EgoSplit #
#################################


@numba.njit(nogil=True)
def _get_data(indptr, indices, data, i, j):
    for index in range(indptr[i], indptr[i + 1]):
        if indices[index] == j:
            return data[index]
    return -1


@numba.njit
def _make_neighbor_sets(indptr, indices):
    neighbors = List(
        [set(indices[indptr[i] : indptr[i + 1]]) for i in range(len(indptr) - 1)]
    )
    return neighbors


@numba.njit
def _make_egonet(i, neighbor_sets, global_indptr, global_indices, global_data):
    egonet_nodes = neighbor_sets[i]
    egonet_old_ids = np.empty(len(egonet_nodes), dtype="int32")
    for i, node in enumerate(egonet_nodes):
        egonet_old_ids[i] = node
    egonet_old_ids.sort()
    new_ids = {node: int32(index) for index, node in enumerate(egonet_old_ids)}
    lil = List.empty_list(int32[:])
    for node in egonet_old_ids:
        egonet_neighbors_old_ids = neighbor_sets[node].intersection(egonet_nodes)
        egonet_neighbors_new_ids = np.empty(
            len(egonet_neighbors_old_ids), dtype="int32"
        )
        for i, old_id in enumerate(egonet_neighbors_old_ids):
            egonet_neighbors_new_ids[i] = new_ids[old_id]
        egonet_neighbors_new_ids.sort()
        lil.append(egonet_neighbors_new_ids)
    indptr = np.empty(len(lil) + 1, dtype="int32")
    indptr[0] = 0
    n_edges = 0
    for i in lil:
        n_edges += len(i)
    indices = np.empty(n_edges, dtype="int32")
    data = np.empty_like(indices, dtype=global_data.dtype)
    for i, neighbors in enumerate(lil):
        indptr[i + 1] = indptr[i] + len(neighbors)
        indices[indptr[i] : indptr[i + 1]] = neighbors

        i_old_id = egonet_old_ids[i]
        neighbors_old_ids = np.empty_like(neighbors)
        for j, n in enumerate(neighbors):
            neighbors_old_ids[j] = egonet_old_ids[n]
        for j, index in enumerate(range(indptr[i], indptr[i + 1])):
            data[index] = _get_data(
                global_indptr,
                global_indices,
                global_data,
                i_old_id,
                neighbors_old_ids[j],
            )
    return indptr, indices, data


@numba.njit
def make_persona_graph(
    g_indptr, g_indices, g_data, egonet_indices, egonet_community, first_personae_index
):
    persona_indptr = np.empty(first_personae_index[-1] + 1, dtype="int32")
    persona_indptr[-1] = len(g_indices)
    persona_indices = np.empty_like(g_indices)
    persona_data = np.empty_like(g_data)

    next_index = 0
    for og_n1 in range(len(g_indptr) - 1):
        og_neighbors = egonet_indices[og_n1]
        communities = egonet_community[og_n1]

        for c in range(np.max(communities) + 1 if len(communities) else 0):
            new_n1 = first_personae_index[og_n1] + c
            new_n1_indptr = next_index
            persona_indptr[new_n1] = new_n1_indptr
            for i in range(len(communities)):
                if communities[i] != c:
                    continue
                og_n2 = og_neighbors[i]
                # Get new id of the other end of the edge (og_n1, og_n2)
                og_n2_neighbors = egonet_indices[og_n2]
                # search for og_n1
                for j in range(len(og_n2_neighbors)):
                    if og_n2_neighbors[j] != og_n1:
                        continue
                    # Get the egonet commuity of og_n1
                    n2_persona_for_n1 = egonet_community[og_n2][j]
                    new_n2 = first_personae_index[og_n2] + n2_persona_for_n1
                    # write new n2_persona and data into persona graph
                    persona_indices[next_index] = new_n2
                    persona_data[next_index] = g_data[g_indptr[og_n1] + i]
                    next_index += 1
    return persona_data, persona_indices, persona_indptr


class EgoSplit:
    """
    Implementation of the Egosplitting framework method for overlapping clustering using
    sknetwork. Since sknetwork does not allow overlapping clusterings, this is not a
    subclass of the sknetwork.clustering.BaseClustering, but it is built to behave similarly.

    Parameters
    ----------
    local_clustering: The clustering method used for the egonet. Should be either "CC"
        (ConnectedCompnents), "PC" (PropagationClustering), or a subclass of
        sknetwork.clustering.BaseClustering.
    global_clustering: The clustering method used for the persona graph. Should
        be either "Louvain", "Leiden", or a subclass of sknetwork.clustering.BaseClustering.
    random_state: The random state to pass to the default clustering algorithms

    Returns
    -------
    scipy.sparse.csr_matrix: An overlapping clustering of the nodes. Rows correspond to clusters
        and columns to nodes.

    Example
    -------
    >>> g = sn.data.karate_club()
    >>> part1 = EgoSplit().fit_predict(g)

    Reference
    ---------
    Alessandro Epasto, Silvio Lattanzi, and Renato Paes Leme. 2017. Ego-Splitting Framework:
    from Non-Overlapping to Overlapping Clusters. In Proceedings of the 23rd ACM SIGKDD
    International Conference on Knowledge Discovery and Data Mining (KDD '17). Association
    for Computing Machinery, New York, NY, USA, 145-154. https://doi.org/10.1145/3097983.3098054
    """

    def __init__(
        self,
        local_clustering="PC",
        global_clustering="Leiden",
        min_cluster_size=5,
        random_state=None,
        verbose=False,
    ):
        if local_clustering == "CC":
            self.local_clustering_ = ConnectedComponents()
        elif local_clustering == "PC":
            self.local_clustering_ = sn.clustering.PropagationClustering()
        elif issubclass(type(local_clustering), sn.clustering.BaseClustering):
            self.local_clustering_ = local_clustering
        else:
            raise ValueError(
                f"local_clustering should be either 'CC' or 'PC', or a subclass of sknetwork.clustering.BaseClustering. Got {type(local_clustering)}"
            )

        if global_clustering == "Leiden":
            self.global_clustering_ = sn.clustering.Leiden(random_state=random_state)
        elif global_clustering == "Louvain":
            self.global_clustering_ = sn.clustering.Louvain(random_state=random_state)
        elif global_clustering == "PC":
            self.global_clustering_ = sn.clustering.PropagationClustering()
        elif issubclass(type(global_clustering), sn.clustering.BaseClustering):
            self.global_clustering_ = global_clustering
        else:
            raise ValueError(
                f"global_clustering should be in ['Louvain', 'Leiden', 'PC'] or a subclass of sknetwork.clustering.BaseClustering. Got {type(global_clustering)}"
            )

        self.min_cluster_size = min_cluster_size
        if not isinstance(self.min_cluster_size, int):
            if self.max_rounds % 1 != 0:
                raise ValueError("min_cluster_size must be a whole number")
            try:
                # convert other types of int to python int
                self.min_cluster_size = int(self.min_cluster_size)
            except ValueError:
                raise ValueError("min_cluster_size must be an int")
        if self.min_cluster_size < 0:
            raise ValueError("min_cluster_size must be non-negative")
        self.verbose = verbose

    def fit(self, g):
        egonet_indices = []  # Store the original indices of the egonet
        egonet_community = []  # Store the community labels of the ego nets
        self.first_personae_index_ = np.empty(
            g.shape[0] + 1, dtype="int32"
        )  # Store the first index for a nodes new personae.
        # The new personae of node i will be stored in rows
        # first_personae_index[i], first_personae_index[i]+1, ... , first_personae_index[i+1]-1.
        next_index = 0
        neighbor_sets = _make_neighbor_sets(g.indptr, g.indices)
        print("Making Egonets") if self.verbose else None
        for node in tqdm(range(g.shape[0]), disable=not self.verbose):
            neighbors = g.indices[g.indptr[node] : g.indptr[node + 1]]
            egonet_indices.append(neighbors)
            indptr, indices, data = _make_egonet(
                node, neighbor_sets, g.indptr, g.indices, g.data
            )
            egonet = sp.csr_matrix(
                (data, indices, indptr), shape=(len(neighbors), len(neighbors))
            )
            if (
                len(egonet.data) == 0
            ):  # egonet has no edges, each node is its own cluster
                persona_map = sp.csgraph.connected_components(egonet)[1]
            else:
                persona_map = self.local_clustering_.fit_predict(egonet).astype("int32")
            egonet_community.append(persona_map)
            self.first_personae_index_[node] = next_index
            next_index += np.max(persona_map) + 1 if len(persona_map) else 0

        self.first_personae_index_[-1] = next_index
        ei = List(egonet_indices)
        ec = List(egonet_community)
        print("Making Persona Graph") if self.verbose else None
        persona_graph_data = make_persona_graph(
            g.indptr, g.indices, g.data, ei, ec, self.first_personae_index_
        )
        self.persona_graph_ = sp.csr_matrix(
            persona_graph_data,
            shape=(self.first_personae_index_[-1], self.first_personae_index_[-1]),
        )
        print("Clustering Persona Graph") if self.verbose else None
        self.persona_clusters_ = self.global_clustering_.fit_predict(
            self.persona_graph_
        )
        print("Mapping Clusters") if self.verbose else None
        n_clusters = np.max(self.persona_clusters_) + 1
        clusters = sp.lil_matrix((g.shape[0], n_clusters), dtype="bool")
        for node in tqdm(range(g.shape[0]), disable=not self.verbose):
            node_clusters = np.unique(
                self.persona_clusters_[
                    self.first_personae_index_[node] : self.first_personae_index_[
                        node + 1
                    ]
                ]
            )
            clusters[node, node_clusters] = True
        clusters = clusters.tocsc().transpose()
        if self.min_cluster_size > 0:
            clusters = clusters[clusters.getnnz(1) >= self.min_cluster_size]

        self.labels_ = clusters
        return self

    def fit_predict(self, g):
        self.fit(g)
        return self.labels_
