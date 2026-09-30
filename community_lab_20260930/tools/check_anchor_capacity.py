"""A diagnostic of the published greedy degree-cover anchor rule, not a
reimplementation/benchmark of Highway and not a proposed new algorithm.
Only Python's standard library is required.
"""
from __future__ import annotations
import itertools
import json
from pathlib import Path


def overlapping_cliques(groups: int, exclusive_per_group: int):
    if groups < 2 or exclusive_per_group < 2:
        raise ValueError('Need >=2 cliques with >=2 exclusive vertices each.')
    n = 1 + groups * exclusive_per_group
    adj = [set() for _ in range(n)]
    planted = []
    for g in range(groups):
        members = {0, *range(1 + g*exclusive_per_group,
                             1 + (g+1)*exclusive_per_group)}
        planted.append(sorted(members))
        for u,v in itertools.combinations(members, 2):
            adj[u].add(v); adj[v].add(u)
    return adj, planted


def greedy_degree_cover(adj: list[set[int]]) -> list[int]:
    """Rule from Highway section 3.2, no restrictive anchor-count cap."""
    covered: set[int] = set()
    anchors = []
    for u in sorted(range(len(adj)), key=lambda v: (-len(adj[v]), v)):
        if u not in covered:
            anchors.append(u)
            covered.add(u)
            covered.update(adj[u])
    return anchors


def neighbor_components(adj: list[set[int]], u: int) -> list[list[int]]:
    """An old ego-component primitive, not a novel recovery algorithm."""
    remaining = set(adj[u]); answer = []
    while remaining:
        root = min(remaining)
        remaining.remove(root)
        component = {root}; queue = [root]
        while queue:
            v = queue.pop()
            new = adj[v] & remaining
            remaining.difference_update(new)
            component.update(new); queue.extend(new)
        answer.append(sorted(component))
    return sorted(answer)


def main() -> None:
    rows = []
    for q in (2, 3, 5):
        for s in (2, 5, 12):
            adj, planted = overlapping_cliques(q, s)
            anchors = greedy_degree_cover(adj)
            contexts = neighbor_components(adj, 0)
            assert anchors == [0]
            assert len(contexts) == q
            assert sorted([sorted([0, *c]) for c in contexts]) == sorted(planted)
            rows.append({
                'groups': q, 'exclusive_vertices_per_group': s,
                'n': len(adj), 'm': sum(map(len,adj))//2,
                'hub_degree': len(adj[0]), 'exclusive_degree': len(adj[1]),
                'greedy_anchors': anchors,
                'maximum_number_of_anchor_id_communities': len(anchors),
                'planted_communities': planted,
                'ego_component_control_recovers_planted_sets': True,
            })
    result = {
        'date': '2026-09-30',
        'scope': 'Nine deterministic mechanism checks. No full Highway execution; no real data; no runtime comparison.',
        'paper': 'https://arxiv.org/html/2607.14531v1',
        'inspected_source': 'https://github.com/GiulioRossetti/cdlib/blob/f054f7ca237e4caed008c8e831f248b7f4bd41e8/cdlib/algorithms/internal/Highway.py',
        'claim': 'In this family degree-cover chooses one shared hub; any downstream output indexed only by original anchors has at most one distinct community. This does not refute all overlap algorithms.',
        'positive_control': 'Removing the ego and taking neighbor connected components is an established primitive and resolves this noiseless family; no novelty claim.',
        'rows': rows,
        'passed': len(rows),
    }
    out = Path(__file__).parent / 'results' / 'anchor_capacity.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks_passed': len(rows), 'results': str(out)}, ensure_ascii=False))

if __name__ == '__main__': main()
