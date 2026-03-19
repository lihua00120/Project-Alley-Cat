"""
Layer 6：垃圾車清運避險
────────────────────────────────────────────────
資料現況說明：
  台南市環保局有垃圾車 GPS 即時系統（臺南環保通 App），
  但該 API 未公開，無法從外部直接串接。

  因此本層採用「班表 + 誤點緩衝」策略：
    - 以台南市環保局公告的清運時段為基準
    - 往前 / 往後各延伸 BUFFER_MIN 分鐘
    - 涵蓋垃圾車可能早到或延誤的情況

誤點緩衝設計：
  標準班表：早班 07:00–09:00，晚班 19:00–21:00
  加上緩衝：06:45–09:15，18:45–21:15（各延伸 15 分鐘）

車道判斷（與 Layer 2 共用 LANE_BYPASS 邏輯）：
  單車道路段：垃圾車停靠作業會完全堵住後方 → 套用懲罰
  多車道路段：貨車可從旁線繞過 → 不懲罰
"""

import osmnx as ox
from datetime import datetime, timedelta
from weights import LAYER6, LANE_BYPASS


# ── 中西區 bounding box ──────────────────────────────────────────────────────
LAT_MIN, LAT_MAX = 22.985, 23.005
LON_MIN, LON_MAX = 120.185, 120.215

# ── 誤點緩衝（分鐘）──────────────────────────────────────────────────────────
BUFFER_MIN = 15


def _in_garbage_window(now: datetime) -> tuple[bool, str]:
    """
    判斷現在是否在「垃圾車清運時段（含誤點緩衝）」內。
    回傳 (是否在時段內, 時段名稱)
    """
    for slot in LAYER6["default_schedule"]:
        # 計算含緩衝的時段邊界（以今天日期為基準）
        start = now.replace(
            hour=slot["hour_start"], minute=0, second=0, microsecond=0
        ) - timedelta(minutes=BUFFER_MIN)

        end = now.replace(
            hour=slot["hour_end"], minute=0, second=0, microsecond=0
        ) + timedelta(minutes=BUFFER_MIN)

        if start <= now <= end:
            return True, slot["label"]

    return False, ""


def _can_bypass(edge_data: dict) -> bool:
    """
    判斷這條路段的貨車能否繞過停在路邊的垃圾車。
    邏輯與 layer2_bus.py 的 _can_bypass 完全相同，
    集中由 LANE_BYPASS（weights.py）控制。
    """
    oneway    = edge_data.get('oneway', False)
    lanes_raw = edge_data.get('lanes')

    if lanes_raw is not None:
        try:
            lanes = int(str(lanes_raw).split(';')[0])
        except (ValueError, TypeError):
            lanes = None
    else:
        lanes = None

    if lanes is None:
        highway = edge_data.get('highway', '')
        if isinstance(highway, list):
            highway = highway[0]
        lanes = LANE_BYPASS["default_lanes"].get(
            highway, LANE_BYPASS["default_lanes_fallback"]
        )

    if oneway:
        return lanes >= LANE_BYPASS["oneway_bypass_lanes"]
    else:
        return lanes >= LANE_BYPASS["twoway_bypass_lanes"]


def apply_garbage_risk(G):
    """
    Layer 6：依垃圾車清運時段（含誤點緩衝）與路段車道數，
    決定是否對路段套用懲罰。

    參數：
        G  - 已含 dynamic_cost 的路網圖

    回傳：
        G        - 更新後的路網圖
        markers  - 地圖標記清單（供 app.py 繪圖）
        active   - bool，是否在清運時段（供 UI 顯示）
        label    - 時段名稱（供 UI 顯示，如「早班」）
    """
    now = datetime.now()
    markers = []

    # ── Step 1：判斷是否在清運時段（含誤點緩衝）────────────────────────────
    in_window, slot_label = _in_garbage_window(now)

    if not in_window:
        # 計算距離下一個清運時段還有多久
        next_slots = []
        for slot in LAYER6["default_schedule"]:
            start_today = now.replace(
                hour=slot["hour_start"], minute=0, second=0, microsecond=0
            ) - timedelta(minutes=BUFFER_MIN)
            if start_today > now:
                next_slots.append((start_today, slot["label"]))

        if next_slots:
            next_slots.sort()
            next_time, next_label = next_slots[0]
            mins_until = int((next_time - now).total_seconds() / 60)
            print(
                f"🗑️ [Layer 6] 現在 {now.strftime('%H:%M')}，"
                f"非清運時段。下一班（{next_label}）約 {mins_until} 分鐘後開始"
            )
        else:
            print(f"🗑️ [Layer 6] 今日清運時段已結束")

        return G, markers, False, ""

    print(
        f"🗑️ [Layer 6] 現在 {now.strftime('%H:%M')} 在「{slot_label}」清運時段"
        f"（含 ±{BUFFER_MIN} 分鐘誤點緩衝），開始套用路段懲罰..."
    )

    # ── Step 2：套用中西區清運路段懲罰 ──────────────────────────────────────
    # 保底清運路段（台南市中西區常見清運路線）
    garbage_locations = [
        {"lat": 22.9966, "lon": 120.1980, "area": "國華街周邊"},
        {"lat": 22.9939, "lon": 120.1937, "area": "神農街周邊"},
        {"lat": 22.9980, "lon": 120.2042, "area": "赤崁樓周邊"},
        {"lat": 22.9946, "lon": 120.2046, "area": "孔廟周邊"},
        {"lat": 22.9961, "lon": 120.1946, "area": "海安路周邊"},
        {"lat": 22.9920, "lon": 120.2010, "area": "中正路商圈"},
        {"lat": 22.9930, "lon": 120.1950, "area": "正興街周邊"},
        {"lat": 22.9903, "lon": 120.2002, "area": "台南公園周邊"},
    ]

    blocked_count  = 0
    passable_count = 0

    for loc in garbage_locations:
        lat = loc["lat"]
        lon = loc["lon"]

        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            continue

        try:
            node = ox.distance.nearest_nodes(G, X=lon, Y=lat)

            for u, v, k, d in G.edges(keys=True, data=True):
                if u == node or v == node:
                    if _can_bypass(d):
                        # 多車道：可繞過，不懲罰
                        passable_count += 1
                    else:
                        # 單車道：垃圾車堵住後方
                        d['dynamic_cost'] = d.get('dynamic_cost', 1.0) * LAYER6["garbage_blocked"]
                        blocked_count += 1

            markers.append({
                "lat":        lat,
                "lon":        lon,
                "area":       loc["area"],
                "time_label": slot_label,
                "buffered":   True,  # 標記使用了誤點緩衝
                "layer":      "garbage",
            })

        except Exception:
            continue

    print(
        f"✅ [Layer 6] 完成：{blocked_count} 條路段被堵（單車道）"
        f"，{passable_count} 條路段可繞過（多車道）"
    )
    return G, markers, True, slot_label