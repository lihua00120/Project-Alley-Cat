import requests
import osmnx as ox
from shapely.geometry import Point
from datetime import datetime
from weights import LAYER2


def apply_bus_risk(G, client_id, client_secret):
    """
    Layer 2：掃描台南公車即時到站資料，對有公車停靠的路段加掛懲罰。
    非行駛時段（22:00 後 / 06:00 前）自動跳過，不加任何懲罰。
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

        for u, v, k, d in G.edges(keys=True, data=True):
            if u in unique_stops or v in unique_stops:
                d['dynamic_cost'] = d.get('dynamic_cost', d.get('length', 1.0)) * LAYER2["bus_stop"]

        print(f"✅ [Layer 2] 已處理 {len(unique_stops)} 個即時公車風險點")

    except Exception as e:
        print(f"❌ [Layer 2] 即時資料失敗: {e}")

    return G