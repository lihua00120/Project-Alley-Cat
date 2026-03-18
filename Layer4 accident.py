import requests
import osmnx as ox
import streamlit as st


# 中西區 bounding box
LAT_MIN, LAT_MAX = 22.985, 23.005
LON_MIN, LON_MAX = 120.185, 120.215


def apply_accident_risk(G, client_id, client_secret):
    """
    Layer 4：從 TDX 抓取台南市即時交通事件（車禍、施工、封路、障礙物），
    對事故位置附近路段套用 ×500 懲罰。

    參數：
        G             - 已含 dynamic_cost 的路網圖
        client_id     - TDX Client ID
        client_secret - TDX Client Secret

    回傳：
        G             - 更新後的路網圖
        markers       - 地圖標記資料 list（供 app.py 繪圖用）
    """
    print("🚨 [Layer 4] 正在抓取即時車禍 / 交通事件...")
    markers = []

    # ── Step 1：取得 Token ────────────────────────────────────────────────────
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
        st.warning(f"⚠️ [Layer 4] Token 取得失敗：{e}")
        return G, markers

    headers = {'authorization': f'Bearer {token}'}

    # ── Step 2：抓取即時交通事件 ──────────────────────────────────────────────
    accident_url = (
        "https://tdx.transportdata.tw/api/advanced/v2/Road/Traffic/Incident"
        "/City/Tainan?$format=JSON"
    )
    try:
        res  = requests.get(accident_url, headers=headers, timeout=15)
        data = res.json()

        if not data:
            print("ℹ️ [Layer 4] 目前台南無即時交通事件")
            return G, markers

        # ── Step 3：篩選中西區範圍 + 套用懲罰 ───────────────────────────────
        incident_count = 0
        for incident in data:
            # TDX 不同事件格式位置欄位略有差異，嘗試兩種格式
            pos = (
                incident.get('StartLinkLocation', {}).get('StartLinkPosition', {})
                or incident.get('IncidentLocation', {}).get('Position', {})
            )
            lat = pos.get('PositionLat')
            lon = pos.get('PositionLon')

            if not lat or not lon:
                continue
            if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
                continue

            incident_type = incident.get('IncidentType', '未知事件')
            description   = incident.get('Description', '')

            try:
                node = ox.distance.nearest_nodes(G, X=lon, Y=lat)
                for u, v, k, d in G.edges(keys=True, data=True):
                    if u == node or v == node:
                        d['dynamic_cost'] = d.get('dynamic_cost', 1.0) * 500

                markers.append({
                    "lat":   lat,
                    "lon":   lon,
                    "type":  incident_type,
                    "desc":  description,
                    "layer": "accident",
                })
                incident_count += 1

            except Exception:
                continue

        print(f"✅ [Layer 4] 中西區內發現 {incident_count} 筆交通事件")

    except Exception as e:
        st.warning(f"⚠️ [Layer 4] 車禍資料抓取失敗：{e}")

    return G, markers