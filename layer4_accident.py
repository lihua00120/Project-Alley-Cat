import requests
import xml.etree.ElementTree as ET
import osmnx as ox
from shapely.geometry import Point
from weights import LAYER4

NS = "https://traffic.transportdata.tw/standard/traffic/schema/"


def _get_token(client_id, client_secret):
    auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    res = requests.post(auth_url, data={
        'grant_type':    'client_credentials',
        'client_id':     client_id,
        'client_secret': client_secret,
    }, timeout=10)
    res.raise_for_status()
    return res.json().get('access_token')


def _geocode(address, token):
    """用 TDX 地理編碼把路段名稱轉成 (lat, lon)"""
    try:
        url = f"https://tdx.transportdata.tw/api/basic/v2/Geocoding?address={address}&format=JSON"
        res = requests.get(url, headers={'authorization': f'Bearer {token}'}, timeout=8)
        geo = res.json().get('Geometry', '')
        if geo.startswith('POINT'):
            lon, lat = map(float, geo.replace('POINT (', '').replace(')', '').split())
            return lat, lon
    except Exception:
        pass
    return None, None


def apply_traffic_risk(G, client_id, client_secret):
    """
    Layer 4：即時道路事件（Live/News）
    - 用 TDX 地理編碼把 Description 轉成座標，只保留中西區範圍內的事件
    - 回傳：(G, markers, alerts)
        markers : 空清單（保持與其他 layer 介面一致）
        alerts  : 中西區事件清單，供 app.py 顯示在頁面最上方
    """
    print("🚦 [Layer 4] 正在取得即時道路事件...")
    markers = []
    alerts  = []

    # 換 Token
    try:
        token = _get_token(client_id, client_secret)
    except Exception as e:
        print(f"❌ [Layer 4] Token 取得失敗：{e}")
        return G, markers, alerts

    headers = {'authorization': f'Bearer {token}'}

    # 取得中西區邊界
    try:
        district_gdf      = ox.geocode_to_gdf("中西區, 台南市, 台灣")
        district_boundary = district_gdf.unary_union.buffer(0.01)
    except Exception:
        district_boundary = None
        print("⚠️ [Layer 4] 邊界取得失敗，不做地理過濾")

    # 事件類型對應
    kind_map = {
        '車禍':     (1, '🚨'),
        '事故':     (1, '🚨'),
        '火災':     (4, '🔥'),
        '施工':     (2, '🚧'),
        '封閉':     (3, '🚧'),
        '封路':     (3, '🚧'),
        '緊急救護': (4, '🚑'),
    }

    try:
        url = "https://tdx.transportdata.tw/api/basic/v2/Road/Traffic/Live/News/City/Tainan?$format=XML"
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        root     = ET.fromstring(res.content)
        news_list = root.findall(f'.//{{{NS}}}News')
        print(f"  📡 Live/News 全市共 {len(news_list)} 筆，開始過濾中西區...")

        for news in news_list:
            title = news.findtext(f'{{{NS}}}Title',       '').strip()
            desc  = news.findtext(f'{{{NS}}}Description', '').strip()
            time  = news.findtext(f'{{{NS}}}PublishTime', '').strip()

            # 地理編碼：用 desc 加上「台南市中西區」前綴，提高準確率
            query    = f"台南市中西區{desc}" if desc else f"台南市中西區{title}"
            lat, lon = _geocode(query, token)

            # 地理過濾：編碼失敗或不在中西區範圍內就跳過
            if lat is None or lon is None:
                continue
            if district_boundary and not Point(lon, lat).within(district_boundary):
                continue

            # 判斷類型
            type_code, icon = 5, '⚠️'
            matched_kind    = title or '其他'
            for kw, (tc, ic) in kind_map.items():
                if kw in title or kw in desc:
                    type_code    = tc
                    icon         = ic
                    matched_kind = kw
                    break

            type_label = LAYER4.get(type_code, ("其他異常", 0))[0]
            time_str   = time[:16].replace('T', ' ') if time else ''

            alerts.append({
                "icon":       icon,
                "kind":       matched_kind,
                "type_label": type_label,
                "title":      title,
                "desc":       desc,
                "time":       time_str,
            })

        print(f"✅ [Layer 4] 中西區事件共 {len(alerts)} 筆")

    except Exception as e:
        print(f"⚠️ [Layer 4] 資料抓取失敗：{e}")

    return G, markers, alerts