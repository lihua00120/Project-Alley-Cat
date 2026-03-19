import requests
import osmnx as ox
from shapely.geometry import Point


def apply_traffic_risk(G, client_id, client_secret):
    """
    Layer 4：即時道路事件避險
    - 來源1：CongestionLevel  路況壅塞水準
    - 來源2：Live/News        最新道路消息（車禍、施工、封路）
    """
    print("🚦 [Layer 4] 正在取得即時道路事件資料...")

    # 1. 自動換 Token
    auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    auth_data = {
        'grant_type': 'client_credentials',
        'client_id': client_id,
        'client_secret': client_secret
    }
    try:
        auth_res = requests.post(auth_url, data=auth_data, timeout=10)
        auth_res.raise_for_status()
        token = auth_res.json().get('access_token')
    except Exception as e:
        print(f"❌ [Layer 4] Token 取得失敗：{e}")
        return G

    headers = {'authorization': f'Bearer {token}'}

    # 取得台南中西區邊界，用來過濾資料點
    try:
        district_gdf = ox.geocode_to_gdf("中西區, 台南市, 台灣")
        district_boundary = district_gdf.unary_union.buffer(0.005)
    except Exception as e:
        print(f"⚠️ [Layer 4] 邊界取得失敗，略過地理過濾：{e}")
        district_boundary = None

    risk_count = 0

    # -------------------------------------------------------
    # 來源1：壅塞水準
    # CongestionLevel: 1=暢通, 2=稍慢, 3=壅塞, 4=嚴重壅塞
    # -------------------------------------------------------
    try:
        url_congestion = (
            "https://tdx.transportdata.tw/api/basic/v2/Road/Traffic/"
            "CongestionLevel/City/Tainan?$format=JSON"
        )
        res = requests.get(url_congestion, headers=headers, timeout=10)
        res.raise_for_status()
        congestion_data = res.json()

        for item in congestion_data:
            level = item.get('CongestionLevel', 1)
            if level < 2:
                continue  # 暢通，不加成本

            # 路段起終點座標取中點
            start = item.get('StartPosition', {})
            end = item.get('EndPosition', {})
            lat_s, lon_s = start.get('PositionLat'), start.get('PositionLon')
            lat_e, lon_e = end.get('PositionLat'), end.get('PositionLon')

            if not all([lat_s, lon_s, lat_e, lon_e]):
                continue

            mid_lat = (lat_s + lat_e) / 2
            mid_lon = (lon_s + lon_e) / 2

            if district_boundary and not Point(mid_lon, mid_lat).within(district_boundary):
                continue

            # 壅塞等級對應成本
            cost_map = {2: 3000, 3: 8000, 4: 15000}
            extra_cost = cost_map.get(level, 3000)

            node = ox.distance.nearest_nodes(G, X=mid_lon, Y=mid_lat)
            for u, v, k, d in G.edges(node, keys=True, data=True):
                d['dynamic_cost'] = d.get('dynamic_cost', d.get('length', 1)) + extra_cost

            risk_count += 1

        print(f"  ✅ 壅塞路段：處理了 {risk_count} 個風險點")

    except Exception as e:
        print(f"  ⚠️ [Layer 4] 壅塞資料抓取失敗：{e}")

    # -------------------------------------------------------
    # 來源2：最新道路消息（車禍、施工、封路）
    # -------------------------------------------------------
    news_count = 0
    try:
        url_news = (
            "https://tdx.transportdata.tw/api/basic/v2/Road/Traffic/"
            "Live/News/City/Tainan?$format=JSON"
        )
        res = requests.get(url_news, headers=headers, timeout=10)
        res.raise_for_status()
        news_data = res.json()

        # 關鍵字判斷嚴重程度
        high_risk_keywords = ['車禍', '事故', '封閉', '封路']
        mid_risk_keywords = ['施工', '養護', '拓寬', '管線']

        for item in news_data:
            title = item.get('Title', '') + item.get('Description', '')

            pos = item.get('StartPosition', {}) or item.get('Position', {})
            lat = pos.get('PositionLat')
            lon = pos.get('PositionLon')

            if not lat or not lon:
                continue

            if district_boundary and not Point(lon, lat).within(district_boundary):
                continue

            # 根據關鍵字決定成本加成
            if any(kw in title for kw in high_risk_keywords):
                extra_cost = 20000
            elif any(kw in title for kw in mid_risk_keywords):
                extra_cost = 8000
            else:
                extra_cost = 3000

            node = ox.distance.nearest_nodes(G, X=lon, Y=lat)
            for u, v, k, d in G.edges(node, keys=True, data=True):
                d['dynamic_cost'] = d.get('dynamic_cost', d.get('length', 1)) + extra_cost

            news_count += 1

        print(f"  ✅ 道路事件：處理了 {news_count} 個風險點（車禍/施工/封路）")

    except Exception as e:
        print(f"  ⚠️ [Layer 4] 道路事件資料抓取失敗：{e}")

    print(f"🚨 [Layer 4] 完成！共處理 {risk_count + news_count} 個風險點")
    return G