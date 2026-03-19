"""
Layer 4：即時交通事件避險
────────────────────────────────────────────────
資料來源：TDX /api/basic/v2/Road/Traffic/RealTimeEvent/City/Tainan
涵蓋事件類型：
    EventType 1 → 車禍事故   懲罰 ×500
    EventType 2 → 道路施工   懲罰 ×80
    EventType 3 → 特殊事件   懲罰 ×200（封路、活動）
    EventType 4 → 天災       懲罰 ×500（積水、崩塌）
    EventType 5 → 其他異常   懲罰 ×100
"""

import requests
import osmnx as ox
import streamlit as st
from weights import LAYER4

# 中西區 bounding box
LAT_MIN, LAT_MAX = 22.985, 23.005
LON_MIN, LON_MAX = 120.185, 120.215



def _get_token(client_id, client_secret):
    auth_url = (
        "https://tdx.transportdata.tw/auth/realms/TDXConnect"
        "/protocol/openid-connect/token"
    )
    res = requests.post(auth_url, data={
        'grant_type':    'client_credentials',
        'client_id':     client_id,
        'client_secret': client_secret,
    }, timeout=10)
    res.raise_for_status()
    return res.json().get('access_token')


def apply_accident_risk(G, client_id, client_secret):
    """
    Layer 4：從 TDX RealTimeEvent API 抓取台南市即時交通事件，
    依事件類型套用不同懲罰倍率。

    參數：
        G             - 已含 dynamic_cost 的路網圖
        client_id     - TDX Client ID
        client_secret - TDX Client Secret

    回傳：
        G        - 更新後的路網圖
        markers  - 地圖標記清單（供 app.py 繪圖用）
    """
    print("🚨 [Layer 4] 正在抓取即時交通事件...")
    markers = []

    # ── Step 1：取得 Token ────────────────────────────────────────────────────
    try:
        token = _get_token(client_id, client_secret)
    except Exception as e:
        st.warning(f"⚠️ [Layer 4] Token 取得失敗：{e}")
        return G, markers

    headers = {'authorization': f'Bearer {token}'}

    # ── Step 2：抓取即時交通事件（basic 版本，一般帳號可用）─────────────────
    url = (
        "https://tdx.transportdata.tw/api/basic/v2"
        "/Road/Traffic/RealTimeEvent/City/Tainan"
        "?$format=JSON"
    )
    try:
        res  = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        st.warning(f"⚠️ [Layer 4] 資料抓取失敗：{e}")
        return G, markers

    if not data:
        print("ℹ️ [Layer 4] 目前台南無即時交通事件")
        return G, markers

    # ── Step 3：篩選中西區 + 依事件類型套用懲罰 ─────────────────────────────
    count = 0
    for event in data:

        # 位置欄位（TDX RealTimeEvent 格式）
        pos = event.get('EventLocation', {}).get('Position', {})
        lat = pos.get('PositionLat')
        lon = pos.get('PositionLon')

        if not lat or not lon:
            continue
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            continue

        event_type_code = event.get('EventType', 5)
        type_name, penalty = LAYER4.get(event_type_code, ("其他異常", 100))
        description = event.get('Description', '')

        try:
            node = ox.distance.nearest_nodes(G, X=lon, Y=lat)
            for u, v, k, d in G.edges(keys=True, data=True):
                if u == node or v == node:
                    d['dynamic_cost'] = d.get('dynamic_cost', 1.0) * penalty

            markers.append({
                "lat":       lat,
                "lon":       lon,
                "type":      type_name,
                "type_code": event_type_code,
                "desc":      description,
                "penalty":   penalty,
                "layer":     "accident",
            })
            count += 1

        except Exception:
            continue

    print(f"✅ [Layer 4] 中西區內發現 {count} 筆交通事件")
    return G, markers