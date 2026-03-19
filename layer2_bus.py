import requests
import osmnx as ox
from shapely.geometry import Point
from datetime import datetime
from weights import LAYER2, LANE_BYPASS


def _can_bypass(edge_data: dict) -> bool:
    """
    判斷這條路段的貨車能否繞過停在路邊的公車。
    與 layer6_garbage.py 使用相同邏輯，集中由 LANE_BYPASS（weights.py）控制。
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


def apply_bus_risk(G, client_id, client_secret):
    """
    Layer 2：掃描台南公車即時到站資料，對有公車停靠的路段加掛懲罰。

    車道判斷：
      - 單車道路段：公車停靠 → 貨車無法通過 → 套用 LAYER2["bus_stop_blocked"]
      - 多車道路段：公車停靠 → 貨車可繞過   → 不懲罰（×1）

    非行駛時段（22:00 後 / 06:00 前）自動跳過。
    """
    current_hour = datetime.now().hour
    if not (6 <= current_hour <= 22):
        print(f"🌙 [Layer 2] 現在 {current_hour} 時，公車未運行，跳過避險層")
        return G

    print("🚌 [Layer 2] 公車行駛時段，正在掃描即時風險...")

    # ── Token ─────────────────────────────────────────────────────────────────
    auth_url = (
        "https://tdx.transportdata.tw/auth/realms/TDXConnect"
        "/protocol/openid-connect/token"
    )
    try:
        auth_res = requests.post(auth_url, data={
            'grant_type':    'client_credentials',
            'client_id':     client_id,
            'client_secret': client_secret,
        }, timeout=10)
        auth_res.raise_for_status()
        token = auth_res.json().get('access_token')
    except Exception as e:
        print(f"❌ [Layer 2] Token 失敗: {e}")
        return G

    headers = {'authorization': f'Bearer {token}'}

    # ── 即時到站資料（5 分鐘內會到站的班次）────────────────────────────────
    eta_url = (
        "https://tdx.transportdata.tw/api/basic/v2/Bus"
        "/EstimatedTimeOfArrival/City/Tainan"
        "?$filter=EstimateTime le 300"
        "&$select=StopPosition,StopName"
        "&$format=JSON"
    )
    try:
        res  = requests.get(eta_url, headers=headers, timeout=15)
        data = res.json()

        district_gdf      = ox.geocode_to_gdf("中西區, 台南市, 台灣")
        district_boundary = district_gdf.unary_union.buffer(0.005)

        active_stop_nodes = []
        for stop in data:
            pos = stop.get('StopPosition', {})
            lat = pos.get('PositionLat')
            lon = pos.get('PositionLon')
            if lat and lon and Point(lon, lat).within(district_boundary):
                active_stop_nodes.append(
                    ox.distance.nearest_nodes(G, X=lon, Y=lat)
                )

        unique_stops = set(active_stop_nodes)
        if not unique_stops:
            print("ℹ️ [Layer 2] 目前中西區無即時公車，不套用懲罰")
            return G

        blocked  = 0
        passable = 0
        for u, v, k, d in G.edges(keys=True, data=True):
            if u in unique_stops or v in unique_stops:
                if _can_bypass(d):
                    # 多車道：貨車可繞過公車，不加懲罰
                    passable += 1
                else:
                    # 單車道：公車停靠會堵死貨車
                    d['dynamic_cost'] = (
                        d.get('dynamic_cost', d.get('length', 1.0))
                        * LAYER2["bus_stop_blocked"]
                    )
                    blocked += 1

        print(
            f"✅ [Layer 2] 完成：{blocked} 條路段被堵（單車道）"
            f"，{passable} 條路段可繞過（多車道）"
        )

    except Exception as e:
        print(f"❌ [Layer 2] 即時資料失敗: {e}")

    return G