"""
Layer 5：人類活動造成的通行不便
────────────────────────────────────────────────
涵蓋三類人流風險：
  1. 觀光景點  — TDX 官方景點 API + 保底清單，依時段套用懲罰倍率
  2. 學校周邊  — 上學 / 放學時段，中西區各國小國中高中
  3. 傳統市場  — 早市尖峰（06:00~10:00），中西區三大市場

時段模型依據：
  - 交通部觀光署歷年旅遊統計
  - 台南市觀光旅遊局遊客行為調查報告
  - 黑貓宅急便官網服務時間公告（週一~週六，13:00前 / 14:00~18:00）
"""

import requests
import osmnx as ox
from datetime import datetime
from shapely.geometry import Point
from weights import LAYER5, LAYER5_SCHOOL, LAYER5_MARKET


# ── 中西區 bounding box ──────────────────────────────────────────────────────
LAT_MIN, LAT_MAX = 22.985, 23.005
LON_MIN, LON_MAX = 120.185, 120.215

# ── 觀光景點保底清單 ──────────────────────────────────────────────────────────
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

# ── 中西區學校清單 ────────────────────────────────────────────────────────────
SCHOOLS = [
    {"name": "忠義國小", "lat": 22.9989, "lon": 120.2015},
    {"name": "協進國小", "lat": 22.9968, "lon": 120.1987},
    {"name": "進學國小", "lat": 22.9921, "lon": 120.2008},
    {"name": "永福國小", "lat": 22.9943, "lon": 120.2051},
    {"name": "成功國小", "lat": 22.9978, "lon": 120.2035},
    {"name": "南大附小", "lat": 22.9956, "lon": 120.1978},
    {"name": "中山國中", "lat": 22.9932, "lon": 120.2071},
    {"name": "建興國中", "lat": 22.9901, "lon": 120.2044},
    {"name": "臺南女中", "lat": 22.9917, "lon": 120.2062},
    {"name": "家齊高中", "lat": 22.9885, "lon": 120.2038},
]

# ── 中西區市場清單 ────────────────────────────────────────────────────────────
MARKETS = [
    {"name": "永樂市場（國華街）", "lat": 22.9981, "lon": 120.1973},
    {"name": "水仙宮市場",         "lat": 22.9993, "lon": 120.1962},
    {"name": "西門市場（大菜市）", "lat": 22.9961, "lon": 120.1988},
]


# ─────────────────────────────────────────────────────────────────────────────
# 內部工具函式
# ─────────────────────────────────────────────────────────────────────────────

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
    """從 TDX 抓取台南市官方觀光景點，篩選中西區範圍"""
    url = (
        "https://tdx.transportdata.tw/api/basic/v2/Tourism/ScenicSpot"
        "/Tainan?$format=JSON"
        "&$select=ScenicSpotName,Position,Class1"
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
            "name":   item.get('ScenicSpotName', '未知景點'),
            "lat":    lat,
            "lon":    lon,
            "type":   spot_type,
            "source": "TDX",
        })
    return spots


def _calc_tourist_penalty(spot_type: str, now: datetime) -> int:
    """觀光景點依類型 × 時段計算懲罰倍率"""
    profiles   = LAYER5.get(spot_type, [])
    is_weekend = now.weekday() >= 5
    h          = now.hour
    best       = 1

    for rule in profiles:
        day_match = (
            rule["day"] == "all"
            or (rule["day"] == "weekend" and is_weekend)
            or (rule["day"] == "weekday" and not is_weekend)
        )
        if day_match and rule["hour_start"] <= h < rule["hour_end"]:
            best = max(best, rule["penalty"])
    return best


def _get_school_status(now: datetime) -> tuple:
    """
    回傳 (label, penalty) 若目前為學校尖峰，否則 (None, 0)
    上學：    07:20 ~ 08:20
    低年級放學：11:20 ~ 12:10
    高年級放學：16:00 ~ 16:50
    """
    if now.weekday() >= 5:   # 週末不上課
        return None, 0

    t = now.hour * 60 + now.minute
    for label, cfg in LAYER5_SCHOOL.items():
        start = cfg["hour_start"] * 60 + cfg["minute_start"]
        end   = cfg["hour_end"]   * 60 + cfg["minute_end"]
        if start <= t <= end:
            return label, cfg["penalty"]
    return None, 0


def _is_market_peak(now: datetime) -> bool:
    """早市：週一到週六 06:00~10:00"""
    if now.weekday() == 6:
        return False
    cfg = LAYER5_MARKET["early_market"]
    return cfg["hour_start"] <= now.hour < cfg["hour_end"]


def _apply_node_penalty(G, lat, lon, extra_cost):
    """對最近節點的所有相鄰邊加上懲罰"""
    node = ox.distance.nearest_nodes(G, X=lon, Y=lat)
    for u, v, k, d in G.edges(keys=True, data=True):
        if u == node or v == node:
            d['dynamic_cost'] = d.get('dynamic_cost', d.get('length', 1)) + extra_cost


# ─────────────────────────────────────────────────────────────────────────────
# 主函式
# ─────────────────────────────────────────────────────────────────────────────

def apply_tourist_risk(G, client_id=None, client_secret=None):
    """
    Layer 5：人類活動造成的通行不便
      - 觀光景點（TDX API + 保底清單）
      - 學校上下學時段
      - 傳統市場早市時段

    回傳：(G, markers, summary)
    """
    now     = datetime.now()
    markers = []
    labels  = []

    try:
        district_gdf      = ox.geocode_to_gdf("中西區, 台南市, 台灣")
        district_boundary = district_gdf.unary_union.buffer(0.008)
    except Exception:
        district_boundary = None

    # ── 1. 觀光景點 ───────────────────────────────────────────────────────────
    spots = []
    if client_id and client_secret:
        try:
            token = _get_tdx_token(client_id, client_secret)
            spots = _fetch_tdx_spots(token)
            print(f"📸 [Layer 5] TDX 抓到 {len(spots)} 個中西區官方景點")
        except Exception as e:
            print(f"⚠️ [Layer 5] TDX 失敗，改用保底清單：{e}")

    if not spots:
        spots = [{**z, "source": "fallback"} for z in FALLBACK_ZONES]
        print(f"📸 [Layer 5] 使用保底景點清單，共 {len(spots)} 個")

    tdx_count = high_count = 0
    for spot in spots:
        penalty = _calc_tourist_penalty(spot["type"], now)
        if penalty <= 1:
            continue
        try:
            _apply_node_penalty(G, spot["lat"], spot["lon"], penalty * 1000)
            if spot.get("source") == "TDX":
                tdx_count += 1
            if penalty >= 15:
                high_count += 1
            markers.append({
                "lat":    spot["lat"],  "lon":    spot["lon"],
                "name":   spot["name"], "type":   spot["type"],
                "penalty": penalty,    "source": spot.get("source", "fallback"),
                "layer":  "tourist",
            })
        except Exception:
            continue

    # ── 2. 學校上下學 ─────────────────────────────────────────────────────────
    school_label, school_penalty = _get_school_status(now)
    if school_label:
        labels.append(f"🏫 {school_label}")
        for school in SCHOOLS:
            if district_boundary and not Point(school["lon"], school["lat"]).within(district_boundary):
                continue
            try:
                _apply_node_penalty(G, school["lat"], school["lon"], school_penalty)
                markers.append({
                    "lat":    school["lat"],  "lon":     school["lon"],
                    "name":   school["name"], "type":    "school",
                    "label":  school_label,   "penalty": school_penalty // 1000,
                    "layer":  "tourist",
                })
            except Exception:
                continue
        print(f"  🏫 [Layer 5] 學校尖峰：{school_label}，{len([m for m in markers if m['type']=='school'])} 所")
    else:
        print(f"  🏫 [Layer 5] 學校：非尖峰時段")

    # ── 3. 傳統市場早市 ───────────────────────────────────────────────────────
    if _is_market_peak(now):
        market_penalty = LAYER5_MARKET["early_market"]["penalty"]
        labels.append(f"🛒 早市尖峰（{now.strftime('%H:%M')}）")
        for market in MARKETS:
            if district_boundary and not Point(market["lon"], market["lat"]).within(district_boundary):
                continue
            try:
                _apply_node_penalty(G, market["lat"], market["lon"], market_penalty)
                markers.append({
                    "lat":    market["lat"],  "lon":     market["lon"],
                    "name":   market["name"], "type":    "market",
                    "label":  "早市尖峰",     "penalty": market_penalty // 1000,
                    "layer":  "tourist",
                })
            except Exception:
                continue
        print(f"  🛒 [Layer 5] 早市尖峰，{len([m for m in markers if m['type']=='market'])} 個市場")
    else:
        print(f"  🛒 [Layer 5] 市場：非尖峰時段")

    # ── 4. 摘要 ───────────────────────────────────────────────────────────────
    is_weekend = now.weekday() >= 5
    time_label = (
        "假日夜間（最高峰）" if is_weekend and now.hour >= 17 else
        "假日白天（高峰）"   if is_weekend else
        "平日夜間（中高峰）" if now.hour >= 17 else
        "平日白天（一般）"
    )
    data_src = f"TDX官方景點 {tdx_count} 個" if tdx_count else "內建保底清單"
    extra    = "、".join(labels) if labels else ""
    summary  = f"現在時段：{time_label}｜{data_src}｜高峰熱區 {high_count} 個"
    if extra:
        summary += f"｜{extra}"

    print(f"✅ [Layer 5] 完成，共 {len(markers)} 個標記")
    return G, markers, summary