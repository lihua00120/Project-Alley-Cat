import requests
import osmnx as ox
from shapely.geometry import Point

def apply_bus_risk(G, client_id, client_secret):
    """
    ✨ 關鍵修正：這裡現在接收 G, client_id, client_secret 共三個參數
    """
    print("🚌 [Layer 2] 正在自動換發 Token 並掃描風險...")

    # 1. 自動換 Token
    auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    auth_data = {
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret
    }

    try:
        auth_res = requests.post(auth_url, data=auth_data)
        auth_res.raise_for_status()
        token = auth_res.json().get('access_token')
    except Exception as e:
        print(f"❌ Token 取得失敗: {e}")
        return G

    # 2. 抓取站牌資料
    headers = {'authorization': f'Bearer {token}'}
    station_url = "https://tdx.transportdata.tw/api/basic/v2/Bus/Station/City/Tainan?%24format=JSON"

    try:
        res = requests.get(station_url, headers=headers)
        data = res.json()

        # 取得邊界過濾
        district_gdf = ox.geocode_to_gdf("中西區, 台南市, 台灣")
        district_boundary = district_gdf.unary_union.buffer(0.005)

        stop_nodes = []
        for station in data:
            pos = station.get('StationPosition', {})
            lat, lon = pos.get('PositionLat'), pos.get('PositionLon')
            if lat and lon and Point(lon, lat).within(district_boundary):
                stop_nodes.append(ox.distance.nearest_nodes(G, X=lon, Y=lat))

        # 3. 注入風險
        unique_stops = set(stop_nodes)
        for u, v, k, d in G.edges(keys=True, data=True):
            if u in unique_stops or v in unique_stops:
                d['dynamic_cost'] += 10000
        print(f"🚨 [Layer 2] 成功！已處理 {len(unique_stops)} 個風險點")

    except Exception as e:
        print(f"❌ 資料抓取失敗: {e}")

    return G
