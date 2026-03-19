"""
Layer 6：垃圾車清運時段避險
────────────────────────────────────────────────
資料來源：台南市環保局清潔車時刻表
API：https://clean.tnepb.gov.tw/

核心邏輯（與 Layer 2 公車共用）：
    垃圾車清運時，貨車是否能通過，取決於路段車道數：
      - 單車道 / 雙向共 2 線以下 → 垃圾車完全堵死後方 → 套用 LAYER6["garbage_blocked"]
      - 雙向 4 線以上 / 單行 2 線以上 → 貨車可從旁繞過 → 不懲罰（×1）

    判斷依據：OSM 的 lanes 屬性 + LANE_BYPASS 設定（weights.py）
"""

import requests
import osmnx as ox
import streamlit as st
from datetime import datetime
from weights import LAYER6, LANE_BYPASS


# ── 中西區 bounding box ──────────────────────────────────────────────────────
LAT_MIN, LAT_MAX = 22.985, 23.005
LON_MIN, LON_MAX = 120.185, 120.215


def _is_garbage_active(now: datetime) -> bool:
    """
    判斷現在是否在垃圾車清運時段。
    優先使用 API 的即時資料；API 失敗時依 weights.py 的預設時段判斷。
    """
    h = now.hour
    for slot in LAYER6["default_schedule"]:
        if slot["hour_start"] <= h < slot["hour_end"]:
            return True
    return False


def _can_bypass(edge_data: dict) -> bool:
    """
    判斷這條路段的貨車能否繞過停在路邊的垃圾車。
    回傳 True = 可繞過（不懲罰），False = 無法繞過（套用懲罰）
    """
    oneway = edge_data.get('oneway', False)

    # 取得車道數：優先用 OSM 標注，沒有就依 highway 等級估算
    lanes_raw = edge_data.get('lanes')
    if lanes_raw is not None:
        try:
            lanes = int(str(lanes_raw).split(';')[0])  # 有些標注格式為 "2;3"
        except (ValueError, TypeError):
            lanes = None
    else:
        lanes = None

    if lanes is None:
        highway = edge_data.get('highway', '')
        if isinstance(highway, list):
            highway = highway[0]
        default_map = LANE_BYPASS["default_lanes"]
        lanes = default_map.get(highway, LANE_BYPASS["default_lanes_fallback"])

    # 判斷是否可繞過
    if oneway:
        return lanes >= LANE_BYPASS["oneway_bypass_lanes"]
    else:
        return lanes >= LANE_BYPASS["twoway_bypass_lanes"]


def _fetch_garbage_routes(now: datetime):
    """
    嘗試從台南市環保局 API 抓取今日清運路線與時間。
    回傳清運路線的地點清單 [{lat, lon, area, time_label}, ...]
    若 API 無法使用，回傳空清單（由呼叫端決定 fallback 策略）。
    """
    routes = []
    try:
        # 台南市環保局清潔車時刻 API
        # 注意：實際 endpoint 需依官方最新文件確認
        url = "https://clean.tnepb.gov.tw/api/GarbageTruck/GetRouteInfo"
        params = {
            "city":     "台南市",
            "district": "中西區",
            "date":     now.strftime("%Y-%m-%d"),
        }
        res  = requests.get(url, params=params, timeout=10)
        data = res.json()

        for item in (data if isinstance(data, list) else []):
            lat = item.get('Lat') or item.get('lat')
            lon = item.get('Lon') or item.get('lon') or item.get('Lng')
            if lat and lon:
                routes.append({
                    "lat":        float(lat),
                    "lon":        float(lon),
                    "area":       item.get('Area', ''),
                    "time_label": item.get('Time', ''),
                })

    except Exception:
        pass  # API 失敗時靜默回傳空清單

    return routes


def apply_garbage_risk(G):
    """
    Layer 6：依垃圾車清運時段與路段車道數，決定是否套用懲罰。

    參數：
        G  - 已含 dynamic_cost 的路網圖（含每條邊的 lanes / highway 資訊）

    回傳：
        G        - 更新後的路網圖
        markers  - 地圖標記清單（供 app.py 繪圖）
        active   - bool，是否在清運時段（供 UI 顯示）
    """
    now = datetime.now()
    markers = []

    # ── Step 1：判斷是否在清運時段 ───────────────────────────────────────────
    if not _is_garbage_active(now):
        h = now.hour
        print(f"🗑️ [Layer 6] 現在 {h} 時，非垃圾車清運時段，跳過")
        return G, markers, False

    print(f"🗑️ [Layer 6] 垃圾車清運時段，開始套用路段懲罰...")

    # ── Step 2：嘗試從 API 取得清運路線 ─────────────────────────────────────
    garbage_locations = _fetch_garbage_routes(now)

    if garbage_locations:
        print(f"✅ [Layer 6] API 取得 {len(garbage_locations)} 個清運地點")
    else:
        # API 失敗：fallback 到中西區常見清運路段（保底清單）
        print("⚠️ [Layer 6] API 無法使用，改用保底清運路段清單")
        garbage_locations = [
            {"lat": 22.9966, "lon": 120.1980, "area": "國華街周邊",   "time_label": "早班"},
            {"lat": 22.9939, "lon": 120.1937, "area": "神農街周邊",   "time_label": "早班"},
            {"lat": 22.9980, "lon": 120.2042, "area": "赤崁樓周邊",   "time_label": "晚班"},
            {"lat": 22.9946, "lon": 120.2046, "area": "孔廟周邊",     "time_label": "晚班"},
            {"lat": 22.9961, "lon": 120.1946, "area": "海安路周邊",   "time_label": "早班"},
            {"lat": 22.9920, "lon": 120.2010, "area": "中正路商圈",   "time_label": "晚班"},
        ]

    # ── Step 3：對每個清運地點的最近路段套用懲罰 ────────────────────────────
    blocked_count  = 0
    passable_count = 0

    for loc in garbage_locations:
        lat = loc["lat"]
        lon = loc["lon"]

        # 中西區範圍外跳過
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            continue

        try:
            node = ox.distance.nearest_nodes(G, X=lon, Y=lat)

            for u, v, k, d in G.edges(keys=True, data=True):
                if u == node or v == node:

                    # ── 核心邏輯：依車道數決定懲罰 ───────────────────────
                    if _can_bypass(d):
                        # 多車道：貨車可繞過垃圾車，不懲罰
                        penalty = LAYER6["garbage_passable"]  # = 1
                        passable_count += 1
                    else:
                        # 單車道：垃圾車堵死後方，套用懲罰
                        penalty = LAYER6["garbage_blocked"]   # = 150
                        blocked_count += 1

                    if penalty > 1:
                        d['dynamic_cost'] = d.get('dynamic_cost', 1.0) * penalty

            markers.append({
                "lat":        lat,
                "lon":        lon,
                "area":       loc.get("area", ""),
                "time_label": loc.get("time_label", ""),
                "layer":      "garbage",
            })

        except Exception:
            continue

    print(
        f"✅ [Layer 6] 完成：{blocked_count} 條路段被堵（單車道）"
        f"，{passable_count} 條路段可繞過（多車道）"
    )
    return G, markers, True