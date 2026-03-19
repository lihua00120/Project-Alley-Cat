import requests
import osmnx as ox
from shapely.geometry import Point


def apply_traffic_risk(G, client_id, client_secret):
    """
    Layer 4：即時道路事件避險
    - 來源1：CongestionLevel  路況壅塞水準
    - 來源2：Live/News        最新道路消息（車禍、施工、封路）
    回傳：(G, markers)  ← 與其他 layer 一致
    """
    print("🚦 [Layer 4] 正在取得即時道路事件資料...")
    markers = []

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
        return G, markers

    headers = {'authorization': f'Bearer {token}'}

    # 取得台南中西區邊界
    try:
        district_gdf = ox.geocode_to_gdf("中西區, 台南市, 台灣")
        district_boundary = district_gdf.unary_union.buffer(0.005)
    except Exception as e:
        print(f"⚠️ [Layer 4] 邊界取得失敗，略過地理過濾：{e}")
        district_boundary = None

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

        cost_map = {2: 3000, 3: 8000, 4: 15000}

        for item in congestion_data:
            level = item.get('CongestionLevel', 1)
            if level < 2:
                continue

            start = item.get('StartPosition', {}) or {}
            end   = item.get('EndPosition',   {}) or {}
            lat_s, lon_s = start.get('PositionLat'), start.get('PositionLon')
            lat_e, lon_e = end.get('PositionLat'),   end.get('PositionLon')

            if not all([lat_s, lon_s, lat_e, lon_e]):
                continue

            mid_lat = (lat_s + lat_e) / 2
            mid_lon = (lon_s + lon_e) / 2

            if district_boundary and not Point(mid_lon, mid_lat).within(district_boundary):
                continue

            extra_cost = cost_map.get(level, 3000)
            node = ox.distance.nearest_nodes(G, X=mid_lon, Y=mid_lat)
            for u, v, k, d in G.edges(keys=True, data=True):
                if u == node or v == node:
                    d['dynamic_cost'] = d.get('dynamic_cost', d.get('length', 1)) + extra_cost

        print(f"  ✅ [Layer 4] 壅塞資料處理完成")

    except Exception as e:
        print(f"  ⚠️ [Layer 4] 壅塞資料抓取失敗：{e}")

    # -------------------------------------------------------
    # 來源2：最新道路消息（車禍、施工、封路）
    # -------------------------------------------------------
    try:
        url_news = (
            "https://tdx.transportdata.tw/api/basic/v2/Road/Traffic/"
            "Live/News/City/Tainan?$format=JSON"
        )
        res = requests.get(url_news, headers=headers, timeout=10)
        res.raise_for_status()
        news_data = res.json()

        # type_code 對應 app.py 裡地圖標記的顏色邏輯
        # 1=車禍(red), 2=施工(gray), 3=封路(orange), 5=其他(orange)
        kind_map = {
            '車禍': (1, 20000), '事故': (1, 20000),
            '封閉': (3, 15000), '封路': (3, 15000),
            '施工': (2,  8000), '養護': (2,  8000),
            '拓寬': (2,  8000), '管線': (2,  8000),
        }

        for item in news_data:
            title = (item.get('Title', '') or '') + (item.get('Description', '') or '')
            pos   = item.get('StartPosition') or item.get('Position') or {}
            lat   = pos.get('PositionLat')
            lon   = pos.get('PositionLon')

            if not lat or not lon:
                continue
            if district_boundary and not Point(lon, lat).within(district_boundary):
                continue

            # 判斷類型
            type_code, extra_cost = 5, 3000
            matched_kind = '其他'
            for kw, (tc, cost) in kind_map.items():
                if kw in title:
                    type_code, extra_cost = tc, cost
                    matched_kind = kw
                    break

            node = ox.distance.nearest_nodes(G, X=lon, Y=lat)
            for u, v, k, d in G.edges(keys=True, data=True):
                if u == node or v == node:
                    d['dynamic_cost'] = d.get('dynamic_cost', d.get('length', 1)) + extra_cost

            markers.append({
                "lat":       lat,
                "lon":       lon,
                "type":      matched_kind,
                "type_code": type_code,
                "desc":      item.get('Description', ''),
                "penalty":   extra_cost // 1000,  # 給地圖 popup 顯示用
                "layer":     "accident",           # 沿用 app.py 裡的 layer 名稱
            })

        print(f"  ✅ [Layer 4] 道路事件處理完成，共 {len(markers)} 筆標記")

    except Exception as e:
        print(f"  ⚠️ [Layer 4] 道路事件資料抓取失敗：{e}")

    print(f"🚨 [Layer 4] 完成！共產生 {len(markers)} 個地圖標記")
    return G, markers