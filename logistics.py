"""
order_router.py — 貨物訂單分配與多車路線規劃
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
# 地圖路線顏色（每台車一個顏色，最多支援 6 台）
TRUCK_COLORS = ["#00E676", "#FF6D00", "#2979FF", "#D500F9", "#FFEA00", "#00BCD4"]


def load_orders(csv_path: str = "logistics.csv") -> pd.DataFrame:
    """讀取訂單 CSV，回傳 DataFrame"""
    for enc in ["utf-8-sig", "cp950", "utf-8"]:
        try:
            df = pd.read_csv(csv_path, encoding=enc, dtype=str).fillna("")
            break
        except Exception:
            df = pd.DataFrame()
    return df


def split_orders_by_slot(df: pd.DataFrame) -> dict:
    """
    依時段分組，回傳：
    {
      "13時前":    [row, ...],
      "不指定":    [row, ...],
      "14時-18時": [row, ...],
    }
    """
    groups = {slot: [] for slot in TIME_SLOT_ORDER}
    for _, row in df.iterrows():
        slot = row.get("time_slot", "不指定").strip()
        if slot not in groups:
            slot = "不指定"
        groups[slot].append(row.to_dict())
    return groups


def assign_trucks(groups: dict, num_trucks: int) -> list:
    """
    將訂單分配給 num_trucks 台貨車。
    規則：
      - 同台車只能同時段
      - 13時前優先分配，其次不指定，最後14時-18時
      - 每個時段內的訂單盡量平均分給可用的貨車
    回傳：
      [
        {"truck_id": 1, "time_slot": "13時前",    "orders": [...]},
        {"truck_id": 2, "time_slot": "不指定",    "orders": [...]},
        ...
      ]
    """
    assignments = []
    truck_id    = 1
    remaining   = num_trucks

    for slot in TIME_SLOT_ORDER:
        orders = groups[slot]
        if not orders or remaining <= 0:
            continue

        # 這個時段需要幾台車（至少 1 台，最多用掉剩餘車輛數）
        # 簡單策略：每台車最多 5 筆，算出需要幾台
        trucks_needed = max(1, -(-len(orders) // 5))  # ceil division
        trucks_for_slot = min(trucks_needed, remaining)

        # 平均分配訂單給這幾台車
        chunk_size = max(1, -(-len(orders) // trucks_for_slot))
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


def geocode_orders(assignments: list, get_location_fn) -> list:
    """
    對每台車的每筆訂單做地理編碼，取得 (lat, lon)。
    get_location_fn: 傳入 app.py 的 get_location() 函式
    回傳同結構，每筆 order 新增 lat, lon 欄位（失敗則跳過）
    """
    result = []
    for truck in assignments:
        geocoded_orders = []
        for order in truck["orders"]:
            try:
                lat, lon = get_location_fn(order["address"])
                geocoded_orders.append({**order, "lat": lat, "lon": lon})
            except Exception:
                pass  # 地址解析失敗就跳過
        if geocoded_orders:
            result.append({**truck, "orders": geocoded_orders})
    return result


def plan_routes(assignments: list, G, start_lat: float, start_lon: float) -> list:
    """
    對每台車跑 greedy_route，產生路線路徑。
    回傳同結構，每台車新增 segments 欄位。
    """
    orig = ox.distance.nearest_nodes(G, X=start_lon, Y=start_lat)
    result = []

    for truck in assignments:
        dest_nodes = []
        for order in truck["orders"]:
            node = ox.distance.nearest_nodes(G, X=order["lon"], Y=order["lat"])
            dest_nodes.append(node)

        ordered_nodes, segments = _greedy_route(G, orig, dest_nodes)

        # 把排序後的節點對應回訂單資訊
        node_to_order = {
            ox.distance.nearest_nodes(G, X=o["lon"], Y=o["lat"]): o
            for o in truck["orders"]
        }

        result.append({
            **truck,
            "ordered_nodes": ordered_nodes,
            "segments":      segments,
            "node_to_order": node_to_order,
        })

    return result


def _greedy_route(G, orig, dest_nodes: list) -> tuple:
    """最近鄰貪婪 TSP：用實際距離選下一站，用 dynamic_cost 走最安全路線"""
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