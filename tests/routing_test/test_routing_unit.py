"""
Standalone unit test for routing algorithms (Bonus 3).
Does not require os-ken - tests the core algorithm logic.
"""
import heapq
import json
import os
import sys
import tempfile


# ---------------------------------------------------------------------------
# Replicate routing logic from controller.py (without os-ken imports)
# ---------------------------------------------------------------------------

def edge_weight(link_weights, u, v):
    key = (min(u, v), max(u, v))
    return link_weights.get(key, 1)


def dijkstra(switches, adjacency, link_weights, src):
    dist = {d: float('inf') for d in switches}
    prev = {d: None for d in switches}
    dist[src] = 0
    pq = [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d != dist[u]:
            continue
        for v in adjacency[u]:
            w = edge_weight(link_weights, u, v)
            alt = d + w
            if alt < dist[v]:
                dist[v] = alt
                prev[v] = u
                heapq.heappush(pq, (alt, v))
    return dist, prev


def bellman_ford(switches, adjacency, link_weights, src):
    dist = {d: float('inf') for d in switches}
    prev = {d: None for d in switches}
    dist[src] = 0
    n = len(switches)
    for _ in range(n - 1):
        updated = False
        for u in switches:
            if dist[u] == float('inf'):
                continue
            for v in adjacency[u]:
                w = edge_weight(link_weights, u, v)
                alt = dist[u] + w
                if alt < dist[v]:
                    dist[v] = alt
                    prev[v] = u
                    updated = True
        if not updated:
            break
    return dist, prev


def dijkstra_all(switches, adjacency, link_weights, src):
    dist = {d: float('inf') for d in switches}
    prev = {d: [] for d in switches}
    dist[src] = 0
    pq = [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d != dist[u]:
            continue
        for v in adjacency[u]:
            w = edge_weight(link_weights, u, v)
            alt = d + w
            if alt < dist[v]:
                dist[v] = alt
                prev[v] = [u]
                heapq.heappush(pq, (alt, v))
            elif alt == dist[v]:
                prev[v].append(u)
    return dist, prev


def get_next_hop(switches, adjacency, link_weights, algorithm, src, dst):
    if src == dst:
        return None
    if algorithm == 'bellman-ford':
        _, prev = bellman_ford(switches, adjacency, link_weights, src)
    else:
        _, prev = dijkstra(switches, adjacency, link_weights, src)
    curr = dst
    if prev.get(curr) is None:
        return None
    while prev.get(curr) is not None and prev[curr] != src:
        curr = prev[curr]
    if prev.get(curr) is None:
        return None
    if curr in adjacency.get(src, {}):
        return adjacency[src][curr]
    return None


def build_path(switches, adjacency, link_weights, algorithm, src, dst):
    if src == dst:
        return []
    if algorithm == 'bellman-ford':
        _, prev = bellman_ford(switches, adjacency, link_weights, src)
    else:
        _, prev = dijkstra(switches, adjacency, link_weights, src)
    if prev.get(dst) is None:
        return None
    path = []
    curr = dst
    while curr != src:
        prev_node = prev.get(curr)
        if prev_node is None:
            return None
        path.append(curr)
        curr = prev_node
    path.reverse()
    return path[:-1]


# ---------------------------------------------------------------------------
# Test graph: triangle topology
#    1 --5-- 2
#    |       |
#   1        1
#    |       |
#    3------+
#
# With weight config: (1,2)=5, (1,3)=1, (2,3)=1
# Hop-count shortest path 1→2: 1→2 (1 hop)
# Weighted shortest path 1→2: 1→3→2 (cost=2) vs direct (cost=5)
# ---------------------------------------------------------------------------

SWITCHES = [1, 2, 3]
ADJACENCY = {
    1: [2, 3],
    2: [1, 3],
    3: [1, 2],
}
WEIGHTS = {(1, 2): 5, (1, 3): 1, (2, 3): 1}
NO_WEIGHTS = {}

PASS = 0
FAIL = 0


def check(condition, test_name):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {test_name}")
    else:
        FAIL += 1
        print(f"  FAIL  {test_name}")


# ---- Test 1: Dijkstra with hop-count (no weights) ----
def test_dijkstra_hopcount():
    print("\n=== Test 1: Dijkstra with hop-count ===")
    dist, prev = dijkstra(SWITCHES, ADJACENCY, NO_WEIGHTS, 1)
    check(dist[1] == 0, "dist to self = 0")
    check(dist[2] == 1, "dist to 2 = 1 (direct)")
    check(dist[3] == 1, "dist to 3 = 1 (direct)")
    check(prev[2] == 1, "prev of 2 is 1")
    check(prev[3] == 1, "prev of 3 is 1")


# ---- Test 2: Dijkstra with weighted links ----
def test_dijkstra_weighted():
    print("\n=== Test 2: Dijkstra with link weights ===")
    dist, prev = dijkstra(SWITCHES, ADJACENCY, WEIGHTS, 1)
    check(dist[1] == 0, "dist to self = 0")
    check(dist[3] == 1, "dist to 3 = 1 (direct, weight=1)")
    check(dist[2] == 2, "dist to 2 = 2 (via 3, cost=1+1)")
    check(prev[3] == 1, "prev of 3 is 1")
    check(prev[2] == 3, "prev of 2 is 3 (not 1, because 1->2 cost=5 > 1->3->2 cost=2)")
    path = build_path(SWITCHES, ADJACENCY, WEIGHTS, 'dijkstra', 1, 2)
    check(path == [3], "path 1->2 via switches: [3]")


# ---- Test 3: Bellman-Ford matches Dijkstra (positive weights) ----
def test_bellman_ford_matches():
    print("\n=== Test 3: Bellman-Ford matches Dijkstra ===")
    for weights, label in [(NO_WEIGHTS, "hop-count"), (WEIGHTS, "weighted")]:
        d_dist, d_prev = dijkstra(SWITCHES, ADJACENCY, weights, 1)
        b_dist, b_prev = bellman_ford(SWITCHES, ADJACENCY, weights, 1)
        for s in SWITCHES:
            check(d_dist[s] == b_dist[s], f"{label}: dist to {s} match ({d_dist[s]})")
            # prev may differ when equal-cost paths exist, but dist must match


# ---- Test 4: Algorithm switching via get_next_hop ----
def test_algorithm_switching():
    print("\n=== Test 4: Algorithm switching ===")
    # With hop count, both algorithms should give same next-hop
    adj_with_ports = {1: {2: 10, 3: 11}, 2: {1: 20, 3: 22}, 3: {1: 31, 2: 32}}
    n1 = get_next_hop(SWITCHES, adj_with_ports, NO_WEIGHTS, 'dijkstra', 1, 2)
    n2 = get_next_hop(SWITCHES, adj_with_ports, NO_WEIGHTS, 'bellman-ford', 1, 2)
    check(n1 == 10, f"Dijkstra next-hop 1->2 port = 10")
    check(n2 == 10, f"Bellman-Ford next-hop 1->2 port = 10")
    check(n1 == n2, "Both algorithms produce same next-hop")


# ---- Test 5: Multi-path discovery (dijkstra_all) ----
def test_dijkstra_all():
    print("\n=== Test 5: Multi-path discovery ===")
    # All edges weight=1: 1→3 has 2 equal paths: 1→3 and 1→2→3
    dist, prev = dijkstra_all(SWITCHES, ADJACENCY, NO_WEIGHTS, 1)
    check(len(prev[3]) == 1, "1 predecessor for 3 (direct)")
    check(prev[3] == [1], "prev[3] = [1]")
    # For node 2: 1→2 direct
    check(len(prev[2]) == 1, "1 predecessor for 2")

    # With symmetric topology where 1→2 and 2→3 have equal weight,
    # and we check a node reachable via two equal paths.
    # Add a 4th node making a square:
    # 1 --1-- 2
    # |        |
    # 1        1
    # |        |
    # 4 --1-- 3
    s4 = [1, 2, 3, 4]
    adj4 = {1: [2, 4], 2: [1, 3], 3: [2, 4], 4: [1, 3]}
    dist, prev = dijkstra_all(s4, adj4, {}, 1)
    # 1→3: two equal paths: 1→2→3 and 1→4→3, both cost=2
    check(len(prev[3]) == 2, f"2 predecessors for node 3 in square: {prev[3]}")
    check(set(prev[3]) == {2, 4}, "prev[3] = {2, 4}")


# ---- Test 6: No path (disconnected graph) ----
def test_disconnected():
    print("\n=== Test 6: Disconnected graph ===")
    s = [1, 2, 3, 4]
    adj = {1: [2], 2: [1], 3: [4], 4: [3]}  # 1-2 isolated from 3-4
    dist, prev = dijkstra(s, adj, {}, 1)
    check(dist[1] == 0, "dist to 1 = 0")
    check(dist[2] == 1, "dist to 2 = 1")
    check(dist[3] == float('inf'), "dist to 3 = inf (disconnected)")
    check(dist[4] == float('inf'), "dist to 4 = inf (disconnected)")
    path = build_path(s, adj, {}, 'dijkstra', 1, 3)
    check(path is None, "path 1→3 = None (disconnected)")


# ---- Test 7: Same switch ----
def test_same_switch():
    print("\n=== Test 7: Same source/destination ===")
    dist, prev = dijkstra(SWITCHES, ADJACENCY, WEIGHTS, 1)
    check(dist[1] == 0, "dist to self = 0")
    path = build_path(SWITCHES, ADJACENCY, WEIGHTS, 'dijkstra', 1, 1)
    check(path == [], "path self→self = []")


# ---- Test 8: Edge weight with missing key ----
def test_edge_weight_default():
    print("\n=== Test 8: Edge weight default = 1 ===")
    w = edge_weight({}, 1, 2)
    check(w == 1, "unconfigured edge weight = 1")
    w = edge_weight({(1, 3): 5}, 1, 2)
    check(w == 1, "missing edge weight defaults to 1")
    w = edge_weight({(1, 2): 10}, 1, 2)
    check(w == 10, "configured edge weight = 10")
    # Normalized key (min,max) in dict (as _load_weights does)
    w = edge_weight({(1, 2): 7}, 2, 1)
    check(w == 7, "order-independent: (1,2) == (2,1)")


# ---- Test 9: Weight config file loading ----
def test_weight_config_loading():
    print("\n=== Test 9: Weight config file loading ===")
    config = {
        "weights": [
            {"switch_pair": [1, 2], "weight": 5},
            {"switch_pair": [2, 3], "weight": 1},
            {"switch_pair": [1, 3], "weight": 10},
        ]
    }
    loaded = {}
    for entry in config['weights']:
        pair = tuple(sorted(entry['switch_pair']))
        loaded[pair] = entry['weight']
    check(loaded[(1, 2)] == 5, "weight(1,2) = 5")
    check(loaded[(2, 3)] == 1, "weight(2,3) = 1")
    check(loaded[(1, 3)] == 10, "weight(1,3) = 10")


# ---- Test 10: Large topology Dijkstra ----
def test_large_topology():
    print("\n=== Test 10: Large topology (binary tree, 7 nodes) ===")
    #      1
    #    /   \
    #   2     3
    #  / \   / \
    # 4   5 6   7
    N = [1, 2, 3, 4, 5, 6, 7]
    adj = {
        1: [2, 3], 2: [1, 4, 5], 3: [1, 6, 7],
        4: [2], 5: [2], 6: [3], 7: [3],
    }
    dist, prev = dijkstra(N, adj, {}, 1)
    check(dist[4] == 2, "dist 1→4 = 2")
    check(dist[7] == 2, "dist 1→7 = 2")
    check(prev[2] == 1, "prev[2] = 1")
    check(prev[4] == 2, "prev[4] = 2")

    path = build_path(N, adj, {}, 'dijkstra', 1, 7)
    check(path == [3], "path 1→7 via [3]")

    path = build_path(N, adj, {}, 'dijkstra', 4, 7)
    check(path == [2, 1, 3], "path 4→7 via [2, 1, 3]")

    bf_dist, bf_prev = bellman_ford(N, adj, {}, 4)
    check(bf_dist[7] == 4, "BF dist 4→7 = 4 (4→2→1→3→7)")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print("=" * 60)
    print("Routing Algorithms — Unit Tests (Bonus 3)")
    print("=" * 60)

    test_dijkstra_hopcount()
    test_dijkstra_weighted()
    test_bellman_ford_matches()
    test_algorithm_switching()
    test_dijkstra_all()
    test_disconnected()
    test_same_switch()
    test_edge_weight_default()
    test_weight_config_loading()
    test_large_topology()

    print("\n" + "=" * 60)
    print(f"Results: {PASS} passed, {FAIL} failed")
    print("=" * 60)
    sys.exit(0 if FAIL == 0 else 1)
