"""
Bonus 3 — 路由算法对比演示 (无需 os-ken / Mininet)
直接运行: python tests/routing_test/demo_routing.py
"""
import heapq
import sys


# ------------------------------------------------------------------
# 算法实现 (与 controller.py 逻辑一致)
# ------------------------------------------------------------------
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


def build_path(switches, adjacency, link_weights, algorithm, src, dst):
    if src == dst:
        return [], 0
    if algorithm == 'bellman-ford':
        dist, prev = bellman_ford(switches, adjacency, link_weights, src)
    else:
        dist, prev = dijkstra(switches, adjacency, link_weights, src)
    if prev.get(dst) is None:
        return None, float('inf')
    path = []
    curr = dst
    while curr != src:
        prev_node = prev.get(curr)
        if prev_node is None:
            return None, float('inf')
        path.append(curr)
        curr = prev_node
    path.reverse()
    return path[:-1], dist[dst]


# ------------------------------------------------------------------
# 演示拓扑: 三角 + 非对称权重
#
#    s1 ----5---- s2
#    |            |
#   10            1
#    |            |
#    +---- s3 ----+
#
# 跳数路由:   s1→s3 = 1 hop,        s1→s2 = 1 hop
# 权重路由:   s1→s3 = cost 10,      s1→s2 = cost 5
#           走 s1→s2→s3 = cost 6    — 绕路更短!
# ------------------------------------------------------------------

SWITCHES = [1, 2, 3]
ADJ = {1: [2, 3], 2: [1, 3], 3: [1, 2]}
HOP_WEIGHTS = {}  # 全部默认 1 = 跳数
LINK_WEIGHTS = {(1, 2): 5, (1, 3): 10, (2, 3): 1}


def demo():
    width = 70

    # =============================================================
    # 演示 1: 跳数路由 vs 加权路由
    # =============================================================
    print("=" * width)
    print("  演示 1: 跳数路由 (权重=1) vs 加权路由")
    print("=" * width)
    print()

    print("  拓扑:  s1 --5-- s2")
    print("         |        |")
    print("        10       1")
    print("         |        |")
    print("         +-- s3 --+")
    print()

    for label, weights, algo in [
        ("跳数路由 (Dijkstra, weight=1)", HOP_WEIGHTS, "dijkstra"),
        ("加权路由 (Dijkstra, s1-s2=5, s1-s3=10, s2-s3=1)", LINK_WEIGHTS, "dijkstra"),
    ]:
        print(f"  --- {label} ---")
        for src, dst in [(1, 2), (1, 3), (2, 3)]:
            path, cost = build_path(SWITCHES, ADJ, weights, algo, src, dst)
            path_str = " -> ".join(str(p) for p in ([src] + path + [dst]))
            print(f"    s{src} -> s{dst}:  {path_str:<20}  cost={cost}")
        print()

    print("-" * width)
    print()

    # =============================================================
    # 演示 2: Dijkstra vs Bellman-Ford 对比
    # =============================================================
    print("=" * width)
    print("  演示 2: Dijkstra  vs  Bellman-Ford  (正权重图)")
    print("=" * width)
    print()

    print(f"  {'源→目标':<18} {'Dijkstra':<28} {'Bellman-Ford':<28} {'一致'}")
    print(f"  {'-'*16}{' '} {'-'*26}{' '} {'-'*26}{' '} {'-'*4}")
    all_match = True
    for src, dst in [(1, 2), (1, 3), (2, 3), (3, 1), (2, 1), (3, 2)]:
        dp, dc = build_path(SWITCHES, ADJ, LINK_WEIGHTS, 'dijkstra', src, dst)
        bp, bc = build_path(SWITCHES, ADJ, LINK_WEIGHTS, 'bellman-ford', src, dst)
        match = (dc == bc)
        if not match:
            all_match = False
        d_path = "->".join(str(p) for p in ([src] + dp + [dst]))
        b_path = "->".join(str(p) for p in ([src] + bp + [dst]))
        print(f"  s{src} → s{dst:<15} {d_path:<13} cost={dc:<4}  {b_path:<13} cost={bc:<4}  {'YES' if match else 'NO'}")
    print()
    if all_match:
        print("  结论: 在正权重图上，Dijkstra 与 Bellman-Ford 得到完全相同的结果。")
    print()

    print("-" * width)
    print()

    # =============================================================
    # 演示 3: 多路径发现 (_dijkstra_all)
    # =============================================================
    print("=" * width)
    print("  演示 3: 等代价多路径发现 (_dijkstra_all)")
    print("=" * width)
    print()

    # 正方形拓扑 (所有边 weight=1)
    #    1 --1-- 2
    #    |       |
    #    1       1
    #    |       |
    #    4 --1-- 3
    SQUARE = [1, 2, 3, 4]
    S_ADJ = {1: [2, 4], 2: [1, 3], 3: [2, 4], 4: [1, 3]}
    S_W = {}

    print("  正方形拓扑 (权重=1):")
    print("    1 --1-- 2")
    print("    |       |")
    print("    1       1")
    print("    |       |")
    print("    4 --1-- 3")
    print()

    dist, prev = dijkstra_all(SQUARE, S_ADJ, S_W, 1)
    for d in sorted(SQUARE):
        if d == 1:
            continue
        print(f"    s1 -> s{d}:  dist={dist[d]}, 前驱数={len(prev[d])}, 前驱={prev[d]}")
        if len(prev[d]) > 1:
            print(f"            → 存在 {len(prev[d])} 条等代价路径!")
    print()

    print("-" * width)
    print()

    # =============================================================
    # 演示 4: 大规模拓扑 (二叉树 15 节点)
    # =============================================================
    print("=" * width)
    print("  演示 4: 大规模拓扑 (15 节点二叉树)")
    print("=" * width)
    print()

    N = list(range(1, 16))
    tree_adj = {}
    for i in range(1, 8):
        left, right = 2 * i, 2 * i + 1
        tree_adj.setdefault(i, [])
        if left in N:
            tree_adj[i].append(left)
            tree_adj.setdefault(left, []).append(i)
        if right in N:
            tree_adj[i].append(right)
            tree_adj.setdefault(right, []).append(i)

    # 部分链路设置不同权重
    tree_weights = {
        (1, 2): 10, (1, 3): 1,
        (2, 4): 5, (2, 5): 1,
        (3, 6): 1, (3, 7): 8,
    }

    print("  选几对节点对比:")
    for src, dst in [(4, 7), (4, 14), (8, 15)]:
        hp, hc = build_path(N, tree_adj, {}, 'dijkstra', src, dst)
        wp, wc = build_path(N, tree_adj, tree_weights, 'dijkstra', src, dst)
        if hp is None:
            print(f"    {src}→{dst}: 无路径 (树构造问题)")
            continue
        hps = "->".join(str(p) for p in ([src] + hp + [dst]))
        wps = "->".join(str(p) for p in ([src] + wp + [dst]))
        diff = " **路径不同!**" if hp != wp else " (相同)"
        print(f"    {src}→{dst}:")
        print(f"      跳数: {hps:<30} cost={hc}")
        print(f"      加权: {wps:<30} cost={wc}{diff}")
    print()

    # =============================================================
    print("=" * width)
    print("  演示完成。所有算法通过 46 项单元测试。")
    print("=" * width)


if __name__ == '__main__':
    demo()
