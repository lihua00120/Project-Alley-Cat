"""
Layer 5：觀光熱區人流避險
────────────────────────────────────────────────
資料來源：
  1. TDX 觀光 API — 抓取台南市中西區官方登錄景點座標（政府資料）
  2. 學術研究時段模型 — 依景點類型 × 星期 × 小時 決定懲罰係數

時段模型說明：
  各景點類型依文獻（交通部觀光署歷年旅遊統計、台南市觀光旅遊局
  遊客行為調查報告）整理出高峰規律：
    - 廟宇古蹟：平日白天（09-17）中度、假日白天高度
    - 夜市/美食街：每日傍晚至深夜（17-23）高度
    - 老街/文青商圈：下午至夜間（14-22）中至高度
    - 一般景點：白天均值
"""

import requests
import osmnx as ox
from datetime import datetime


# ── 中西區 bounding box ──────────────────────────────────────────────────────
LAT_MIN, LAT_MAX = 22.985, 23.005
LON_MIN, LON_MAX = 120.185, 120.215

# ── 景點類型時段係數表 ────────────────────────────────────────────────────────
# 結構：{ 類型代號: { (weekday, hour_start, hour_end): penalty } }
# weekday: 0-4=平日, 5-6=假日, None=每天
# penalty: 懲罰倍率（乘在 dynamic_cost 上）

CROWD_PROFILE = {
    "temple":   [   # 廟宇、古蹟（赤崁樓、孔廟等）
        {"day": "weekday", "hour_start":  9, "hour_end": 17, "penalty":  8},
        {"day": "weekend", "hour_start":  9, "hour_end": 18, "penalty": 20},
        {"day": "all",     "hour_start": 17, "hour_end": 21, "penalty": 12},
    ],
    "nightmarket": [  # 夜市、美食街（國華街、武聖夜市等）
        {"day": "all",     "hour_start": 17, "hour_end": 23, "penalty": 25},
        {"day": "weekend", "hour_start": 12, "hour_end": 17, "penalty": 12},
        {"day": "weekday", "hour_start": 12, "hour_end": 17, "penalty":  5},
    ],
    "oldstreet": [  # 老街、文青商圈（神農街、正興街、海安路）
        {"day": "all",     "hour_start": 18, "hour_end": 23, "penalty": 20},
        {"day": "weekend", "hour_start": 14, "hour_end": 18, "penalty": 15},
        {"day": "weekday", "hour_start": 14, "hour_end": 18, "penalty":  8},
    ],
    "landmark": [   # 一般地標商圈（林百貨、台南火車站周邊）
        {"day": "weekend", "hour_start": 10, "hour_end": 21, "penalty": 15},
        {"day": "weekday", "hour_start": 12, "hour_end": 18, "penalty":  6},
    ],
    "park": [       # 公園、廣場
        {"day": "weekend", "hour_start":  8, "hour_end": 18, "penalty": 10},
        {"day": "weekday", "hour_start":  7, "hour_end":  9, "penalty":  5},
        {"day": "weekday", "hour_start": 17, "hour_end": 19, "penalty":  5},
    ],
}

# ── 人工標注的中西區重要景點（TDX API 抓到後會疊加，這裡是保底清單）──────────
# 若 TDX 抓取失敗，仍可使用此清單確保系統正常運作
FALLBACK_ZONES = [
    {"name": "赤崁樓",   "lat": 22.9980, "lon": 120.2042, "type": "temple"},
    {"name": "孔廟",     "lat": 22.9946, "lon": 120.2046, "type": "temple"},
    {"name": "國華街",   "lat": 22.9966, "lon": 120.1980, "type": "nightmarket"},
    {"name": "神農街",   "lat": 22.9939, "lon": 120.1937, "type": "oldstreet"},
    {"name": "正興街",   "lat": 22.9930, "lon": 120.1950, "type": "oldstreet"},
    {"name": "海安路",   "lat": 22.9961, "lon": 120.1946, "type": "oldstreet"},
    {"name": "林百貨",   "lat": 22.9920, "lon": 120.2010, "type": "landmark"},
    {"name": "台南公園", "lat": 22.9903, "lon": 120.2002, "type": "park"},
]


def _get_tdx_token(client_id, client_secret):
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


def _fetch_tdx_spots(token):
    """從 TDX 抓取台南市官方觀光景點，篩選中西區範圍，回傳景點清單"""
    url = (
        "https://tdx.transportdata.tw/api/basic/v2/Tourism/ScenicSpot"
        "/Tainan?$format=JSON"
        "&$select=ScenicSpotName,Position,Class1,OpenTime"
    )
    headers = {'authorization': f'Bearer {token}'}
    res  = requests.get(url, headers=headers, timeout=15)
    data = res.json()

    spots = []
    for item in data:
        pos = item.get('Position', {})
        lat = pos.get('PositionLat')
        lon = pos.get('PositionLon')
        if not lat or not lon:
            continue
        if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
            continue

        # 依 TDX 景點分類對應到我們的時段模型類型
        class1 = item.get('Class1', '')
        if '廟' in class1 or '古蹟' in class1 or '寺' in class1 or '祠' in class1:
            spot_type = 'temple'
        elif '夜市' in class1 or '市場' in class1:
            spot_type = 'nightmarket'
        elif '老街' in class1 or '商圈' in class1:
            spot_type = 'oldstreet'
        elif '公園' in class1 or '廣場' in class1:
            spot_type = 'park'
        else:
            spot_type = 'landmark'

        spots.append({
            "name": item.get('ScenicSpotName', '未知景點'),
            "lat":  lat,
            "lon":  lon,
            "type": spot_type,
            "source": "TDX",
        })

    return spots


def _calc_penalty(spot_type: str, now: datetime) -> int:
    """
    依景點類型 × 現在時間，查詢時段係數表，回傳懲罰倍率。
    若現在不在任何高峰時段，回傳 1（不加懲罰）。
    """
    profiles = CROWD_PROFILE.get(spot_type, [])
    is_weekend = now.weekday() >= 5
    h = now.hour
    best = 1

    for rule in profiles:
        day_match = (
            rule["day"] == "all"
            or (rule["day"] == "weekend" and is_weekend)
            or (rule["day"] == "weekday" and not is_weekend)
        )
        hour_match = rule["hour_start"] <= h < rule["hour_end"]
        if day_match and hour_match:
            best = max(best, rule["penalty"])

    return best


def apply_tourist_risk(G, client_id=None, client_secret=None):
    """
    Layer 5：對台南中西區觀光景點附近路段套用時段性懲罰。

    資料優先順序：
      1. 若有 TDX 金鑰 → 從 TDX 觀光 API 抓取官方景點座標
      2. 若 TDX 失敗或無金鑰 → 使用內建保底清單

    懲罰倍率：依景點類型 × 星期 × 小時 動態決定（最低 ×1，最高 ×25）

    回傳：
        G        - 更新後的路網圖
        markers  - 地圖標記清單（供 app.py 繪圖）
        summary  - 摘要字串（供 UI 顯示）
    """
    now = datetime.now()
    markers = []

    # ── Step 1：嘗試從 TDX 抓景點 ─────────────────────────────────────────────
    spots = []
    if client_id and client_secret:
        try:
            token = _get_tdx_token(client_id, client_secret)
            spots = _fetch_tdx_spots(token)
            print(f"📸 [Layer 5] TDX 抓到 {len(spots)} 個中西區官方景點")
        except Exception as e:
            print(f"⚠️ [Layer 5] TDX 抓取失敗，改用保底清單：{e}")

    # TDX 沒抓到就用保底清單
    if not spots:
        spots = [{**z, "source": "fallback"} for z in FALLBACK_ZONES]
        print(f"📸 [Layer 5] 使用保底景點清單，共 {len(spots)} 個")

    # ── Step 2：計算當前時段懲罰並套入路網 ──────────────────────────────────
    tdx_count  = 0
    high_count = 0

    for spot in spots:
        penalty = _calc_penalty(spot["type"], now)
        if penalty <= 1:
            continue   # 非高峰時段，不套用懲罰

        try:
            node = ox.distance.nearest_nodes(G, X=spot["lon"], Y=spot["lat"])
            for u, v, k, d in G.edges(keys=True, data=True):
                if u == node or v == node:
                    d['dynamic_cost'] = d.get('dynamic_cost', 1.0) * penalty

            if spot.get("source") == "TDX":
                tdx_count += 1
            if penalty >= 15:
                high_count += 1

            markers.append({
                "lat":     spot["lat"],
                "lon":     spot["lon"],
                "name":    spot["name"],
                "type":    spot["type"],
                "penalty": penalty,
                "source":  spot.get("source", "fallback"),
                "layer":   "tourist",
            })
        except Exception:
            continue

    # ── Step 3：產生摘要 ────────────────────────────────────────────────────
    is_weekend = now.weekday() >= 5
    time_label = (
        "假日夜間（最高峰）" if is_weekend and now.hour >= 17 else
        "假日白天（高峰）"   if is_weekend else
        "平日夜間（中高峰）" if now.hour >= 17 else
        "平日白天（一般）"
    )
    data_src = f"TDX官方景點 {tdx_count} 個" if tdx_count else "內建保底清單"
    summary  = f"現在時段：{time_label}｜{data_src}｜高峰熱區 {high_count} 個"

    print(f"✅ [Layer 5] 完成，套用 {len(markers)} 個景點懲罰")
    return G, markers, summary