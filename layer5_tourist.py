import osmnx as ox
from datetime import datetime


# 台南中西區觀光熱區定義
# 格式：(緯度, 經度, 名稱, 說明)
TOURIST_ZONES = [
    (22.9966, 120.1980, "國華街",   "府城美食一級戰區，人潮密集"),
    (22.9961, 120.1946, "海安路",   "藝術街道，夜間人潮多"),
    (22.9980, 120.2042, "赤崁樓",   "台南地標，觀光客聚集"),
    (22.9946, 120.2046, "孔廟商圈", "府中街周邊，假日人潮多"),
    (22.9939, 120.1937, "神農街",   "老街，夜間攝影人潮多"),
    (22.9930, 120.1950, "正興街",   "文青商圈，下午至夜間擁擠"),
    (22.9920, 120.2010, "林百貨",   "台南代表景點，市區核心"),
    (22.9903, 120.2002, "台南公園", "假日市集舉辦地"),
]

# 懲罰倍率對照表
PENALTY_MAP = {
    'low':    3,   # 平日早上：遊客少
    'medium': 8,   # 平日下午：中度人潮
    'high':   20,  # 假日 / 夜間：最擁擠
}


def auto_detect_level() -> str:
    """
    根據現在的時間與星期自動判斷觀光熱度等級。
    回傳 'low' / 'medium' / 'high'
    """
    now        = datetime.now()
    is_weekend = now.weekday() >= 5      # 週六 = 5, 週日 = 6
    is_night   = 17 <= now.hour <= 22    # 下午 5 點到 10 點

    if is_weekend or is_night:
        return 'high'
    elif now.hour >= 12:
        return 'medium'
    else:
        return 'low'


def apply_tourist_risk(G, penalty_level: str = None):
    """
    Layer 5：對台南中西區觀光熱區附近路段加掛懲罰權重。

    參數：
        G             - 已含 dynamic_cost 的路網圖
        penalty_level - 'low' / 'medium' / 'high'
                        傳入 None 時自動根據時間判斷

    回傳：
        G             - 更新後的路網圖
        markers       - 地圖標記資料 list（供 app.py 繪圖用）
        level         - 實際套用的等級（供 UI 顯示用）
    """
    # 未指定等級時自動偵測
    if penalty_level is None:
        penalty_level = auto_detect_level()

    penalty = PENALTY_MAP.get(penalty_level, 8)
    markers = []

    print(f"📸 [Layer 5] 觀光熱度：{penalty_level}（×{penalty}），共 {len(TOURIST_ZONES)} 個熱區")

    for lat, lon, name, desc in TOURIST_ZONES:
        try:
            node = ox.distance.nearest_nodes(G, X=lon, Y=lat)
            for u, v, k, d in G.edges(keys=True, data=True):
                if u == node or v == node:
                    d['dynamic_cost'] = d.get('dynamic_cost', 1.0) * penalty

            markers.append({
                "lat":     lat,
                "lon":     lon,
                "name":    name,
                "desc":    desc,
                "penalty": penalty,
                "level":   penalty_level,
                "layer":   "tourist",
            })

        except Exception:
            continue

    print(f"✅ [Layer 5] 完成，已處理 {len(markers)} 個觀光熱區")
    return G, markers, penalty_level