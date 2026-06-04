"""
NetworkX Visualization — Complex Topology with Shortest Paths

Usage: python tests/complex_test/visualize.py
Output: topology.png (rendered graph)

Labels all host-to-host and switch-to-switch shortest paths.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/../..')

try:
    import networkx as nx
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except ImportError:
    print("Error: pip install networkx matplotlib")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Dijkstra (same as controller.py)
# ---------------------------------------------------------------------------
import heapq


def dijkstra(switches, adjacency, src):
    dist = {d: float('inf') for d in switches}
    prev = {d: None for d in switches}
    dist[src] = 0
    pq = [(0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d != dist[u]:
            continue
        for v in adjacency.get(u, {}):
            alt = d + 1
            if alt < dist[v]:
                dist[v] = alt
                prev[v] = u
                heapq.heappush(pq, (alt, v))
    return dist, prev


def build_path(src, dst, prev):
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
    return path


# ---------------------------------------------------------------------------
# Topology: 8 switches + 8 hosts
# ---------------------------------------------------------------------------

SWITCHES = [1, 2, 3, 4, 5, 6, 7, 8]
HOSTS = [1, 2, 3, 4, 5, 6, 7, 8]

# Switch-to-switch adjacency
ADJ = {
    1: {2: None, 3: None, 4: None},
    2: {1: None, 3: None, 5: None},
    3: {1: None, 2: None, 4: None, 6: None},
    4: {1: None, 3: None, 5: None, 7: None},
    5: {2: None, 4: None, 6: None, 8: None},
    6: {3: None, 5: None, 7: None},
    7: {4: None, 6: None, 8: None},
    8: {5: None, 7: None},
}

# Host-to-switch mapping
HOST_SWITCH = {1: 1, 7: 1,  2: 4,  3: 3,  4: 5,  5: 8, 6: 8, 8: 7}


def draw_topology():
    G = nx.Graph()

    for i, sw in enumerate(SWITCHES):
        angle = 2 * 3.14159 * i / len(SWITCHES) - 3.14159 / 2
        x = 4 * (i % 3) + (i // 3) * 1.5
        y = -3 * (i // 3)
        G.add_node(f's{sw}', pos=(x, y), label=f's{sw}', color='lightblue', node_type='switch')

    for h in HOSTS:
        sw = HOST_SWITCH[h]
        x, y = G.nodes[f's{sw}']['pos']
        offset_x = (h % 3 - 1) * 1.5
        offset_y = -1.5 if h <= 4 else 1.5
        G.add_node(f'h{h}', pos=(x + offset_x, y + offset_y),
                   label=f'h{h}', color='lightgreen', node_type='host')
        G.add_edge(f'h{h}', f's{sw}', style='dashed', color='gray')

    for u, neighbors in ADJ.items():
        for v in neighbors:
            if u < v:
                G.add_edge(f's{u}', f's{v}', style='solid', color='black')

    pos = nx.get_node_attributes(G, 'pos')

    fig, ax = plt.subplots(1, 1, figsize=(14, 10))

    node_colors = [G.nodes[n].get('color', 'gray') for n in G.nodes()]
    edge_colors = [G[u][v].get('color', 'gray') for u, v in G.edges()]
    edge_styles = [G[u][v].get('style', 'solid') for u, v in G.edges()]

    nx.draw(G, pos, ax=ax, with_labels=True, node_color=node_colors,
            edge_color=edge_colors, style=edge_styles,
            font_size=8, node_size=800)
    ax.set_title('Complex Topology (8 switches + 8 hosts)')

    switch_ids = sorted(SWITCHES)
    path_texts = []
    for i, sa in enumerate(switch_ids):
        for sb in switch_ids[i + 1:]:
            _, prev = dijkstra(SWITCHES, ADJ, sa)
            path = build_path(sa, sb, prev)
            if path:
                edges_count = len(path)
                path_str = '->'.join(f's{p}' for p in [sa] + path)
                path_texts.append(f's{sa}->s{sb}: {path_str} ({edges_count} edges)')

    text = '\n'.join(path_texts)
    fig.text(0.02, 0.02, text, fontsize=6, fontfamily='monospace',
             verticalalignment='bottom', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    plt.tight_layout()
    output = os.path.join(os.path.dirname(__file__), 'topology.png')
    plt.savefig(output, dpi=150, bbox_inches='tight')
    print(f"Saved: {output}")
    print(f"\nSwitch-to-switch paths:\n{text}")


if __name__ == '__main__':
    draw_topology()
