"""
logistics.py — 貨物訂單分配與多車路線規劃
════════════════════════════════════════════════════════
功能：
  1. 讀取 logistics.csv
  2. 依時段分組（13時前 > 不指定 > 14時-18時）
  3. 依貨車數量平均分配訂單
  4. 每台車各自跑 greedy_route 產生路線
════════════════════════════════════════════════════════
"""

import pandas as pd
import networkx as nx
import osmnx as ox

# 時段顯示名稱與優先順序
TIME_SLOT_ORDER = ["13時前", "不指定", "14時-18時"]
TIME_SLOT_LABEL = {
    "13時前":    "🕐 13時前",
    "不指定":    "📦 不指定",
    "14時-18時": "🕔 14時-18時",
}
TRUCK_COLORS = ["#00E676", "#FF6D00", "#2979FF", "#D500F9", "#FFEA00", "#00BCD4"]


# ─────────────────────────────────────────────────────────────────────────────
# 主要道路節點（模組層級，供 app.py import）
# ─────────────────────────────────────────────────────────────────────────────
def nearest_main_road_node(G, lat: float, lon: float):
    """
    優先找主要道路（primary / secondary / tertiary / trunk）上的最近節點。
    找不到主要道路節點時 fallback 回一般 nearest_nodes。
    """
    main_types = {'primary', 'secondary', 'tertiary', 'trunk'}

    main_nodes = set()
    for u, v, data in G.edges(data=True):
        hw = data.get('highway', '')
        if isinstance(hw, list):
            hw = hw[0]
        if hw in main_types:
            main_nodes.add(u)
            main_nodes.add(v)

    if not main_nodes:
        return ox.distance.nearest_nodes(G, X=lon, Y=lat)

    min_dist  = float('inf')
    best_node = None
    for node in main_nodes:
        n_lat = G.nodes[node]['y']
        n_lon = G.nodes[node]['x']
        dist  = (n_lat - lat) ** 2 + (n_lon - lon) ** 2
        if dist < min_dist:
            min_dist  = dist
            best_node = node

    return best_node


# ─────────────────────────────────────────────────────────────────────────────
# 訂單讀取
# ─────────────────────────────────────────────────────────────────────────────
def load_orders(csv_path: str = "logistics.csv") -> pd.DataFrame:
    for enc in ["utf-8-sig", "cp950", "utf-8"]:
        try:
            df = pd.read_csv(csv_path, encoding=enc, dtype=str).fillna("")
            break
        except Exception:
            df = pd.DataFrame()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 時段分組
# ─────────────────────────────────────────────────────────────────────────────
def split_orders_by_slot(df: pd.DataFrame) -> dict:
    groups = {slot: [] for slot in TIME_SLOT_ORDER}
    for _, row in df.iterrows():
        slot = row.get("time_slot", "不指定").strip()
        if slot not in groups:
            slot = "不指定"
        groups[slot].append(row.to_dict())
    return groups


# ─────────────────────────────────────────────────────────────────────────────
# 貨車分配
# ─────────────────────────────────────────────────────────────────────────────
def assign_trucks(groups: dict, num_trucks: int) -> list:
    assignments = []
    truck_id  = 1
    remaining = num_trucks

    for slot in TIME_SLOT_ORDER:
        orders = groups[slot]
        if not orders or remaining <= 0:
            continue

        trucks_needed   = max(1, -(-len(orders) // 5))
        trucks_for_slot = min(trucks_needed, remaining)
        chunk_size      = max(1, -(-len(orders) // trucks_for_slot))

        for i in range(trucks_for_slot):
            chunk = orders[i * chunk_size: (i + 1) * chunk_size]
            if not chunk:
                break
            assignments.append({
                "truck_id":  truck_id,
                "time_slot": slot,
                "orders":    chunk,
                "color":     TRUCK_COLORS[(truck_id - 1) % len(TRUCK_COLORS)],
            })
            truck_id  += 1
            remaining -= 1

    return assignments


# ─────────────────────────────────────────────────────────────────────────────
# 地理編碼
# ─────────────────────────────────────────────────────────────────────────────
def geocode_orders(assignments: list, get_location_fn) -> list:
    result = []
    for truck in assignments:
        geocoded_orders = []
        for order in truck["orders"]:
            try:
                lat, lon = get_location_fn(order["address"])
                geocoded_orders.append({**order, "lat": lat, "lon": lon})
            except Exception:
                pass
        if geocoded_orders:
            result.append({**truck, "orders": geocoded_orders})
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 路線規劃
# ─────────────────────────────────────────────────────────────────────────────
def plan_routes(assignments: list, G, start_lat: float, start_lon: float) -> list:
    orig   = nearest_main_road_node(G, start_lat, start_lon)
    result = []

    for truck in assignments:
        dest_nodes = []
        for order in truck["orders"]:
            node = nearest_main_road_node(G, order["lat"], order["lon"])
            dest_nodes.append(node)

        ordered_nodes, segments = _greedy_route(G, orig, dest_nodes)

        node_to_order = {
            nearest_main_road_node(G, o["lat"], o["lon"]): o
            for o in truck["orders"]
        }

        result.append({
            **truck,
            "ordered_nodes": ordered_nodes,
            "segments":      segments,
            "node_to_order": node_to_order,
        })

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 貪婪 TSP
# ─────────────────────────────────────────────────────────────────────────────
def _greedy_route(G, orig, dest_nodes: list) -> tuple:
    remaining = list(dest_nodes)
    current   = orig
    order     = []
    segments  = []

    while remaining:
        best_node, best_dist, best_path = None, float('inf'), []
        for cand in remaining:
            try:
                dist = nx.shortest_path_length(G, current, cand, weight='length')
                if dist < best_dist:
                    best_dist = dist
                    best_node = cand
                    best_path = nx.shortest_path(G, current, cand, weight='dynamic_cost')
            except nx.NetworkXNoPath:
                continue
        if best_node is None:
            break
        order.append(best_node)
        segments.append(best_path)
        remaining.remove(best_node)
        current = best_node

    return order, segments