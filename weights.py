"""
weights.py — 全系統避險權重集中管理
════════════════════════════════════════════════════════
所有 Layer 的懲罰倍率都在這裡定義。
日後調整只需改這一個檔案，不需要動 app.py / layer2~6。

懲罰倍率的意義：
    dynamic_cost = 實際路段距離(m) × 各層倍率連乘
    倍率越高 → 路由演算法越傾向繞開該路段
    倍率 = 1 → 不加任何懲罰（正常通行）
════════════════════════════════════════════════════════
"""

# ─────────────────────────────────────────────────────────────────────────────
# 車道數判斷：能否繞過障礙物（公車 / 垃圾車）
# ─────────────────────────────────────────────────────────────────────────────
# 邏輯：當公車或垃圾車停在路邊時，貨車是否有辦法從旁邊通過？
#
#   雙向道 + 總車道 ≥ 4（各方向至少 2 線）→ 可繞過 → Layer 2 / Layer 6 懲罰 ×1
#   單行道 + 車道數 ≥ 2                  → 可繞過 → Layer 2 / Layer 6 懲罰 ×1
#   其他（單車道、窄路）                   → 被堵死 → 正常套用懲罰
#
# 若 OSM 未標注 lanes，依 highway 等級估算：
#   primary / trunk         → 預設 4 線（可繞過）
#   secondary               → 預設 2 線（單向則可繞，雙向則不確定）
#   tertiary / residential  → 預設 2 線雙向（不可繞過）
#   其餘（service 以下）    → 預設 1 線（不可繞過）

LANE_BYPASS = {
    # 能繞過時，Layer 2 / Layer 6 的懲罰倍率直接設為 1（不懲罰）
    "bypass_multiplier": 1,

    # 雙向道：總車道數達此值以上 → 可繞過
    "twoway_bypass_lanes": 4,

    # 單行道：車道數達此值以上 → 可繞過
    "oneway_bypass_lanes": 2,

    # highway 等級預設車道數（OSM 沒有標注 lanes 時使用）
    "default_lanes": {
        "motorway":     6,
        "trunk":        4,
        "primary":      4,
        "secondary":    2,
        "tertiary":     2,
        "residential":  2,
        "service":      1,
        "living_street":1,
        "alley":        1,
        "track":        1,
        "path":         1,
        "unclassified": 2,
    },
    "default_lanes_fallback": 2,   # 完全未知的等級，保守估計 2 線
}

# ─────────────────────────────────────────────────────────────────────────────
# 靜態路網權重（load_base_graph，app.py）
# ─────────────────────────────────────────────────────────────────────────────
STATIC = {
    "narrow_road": 5,    # 窄巷 / 小路（living_street, alley, track, path）
    "dead_end":    10,   # 死巷節點
    # 單行道：不加懲罰（OSM 已限制逆向，懲罰反而讓路由走小路）
}

# ─────────────────────────────────────────────────────────────────────────────
# Layer 2：公車即時避險（layer2_bus.py）
# ─────────────────────────────────────────────────────────────────────────────
LAYER2 = {
    "bus_stop_blocked":  5,   # 單車道：公車停靠，貨車無法通過 → 懲罰
    "bus_stop_passable": 1,   # 多車道：貨車可繞過公車 → 不懲罰
}

# ─────────────────────────────────────────────────────────────────────────────
# Layer 3：廟會 / 人為管制（app.py → apply_event_risk）
# 資料來源：table_result.csv（台南市道路使用申請核准資料）
# ─────────────────────────────────────────────────────────────────────────────
LAYER3 = {
    "廟會宴客": 200,     # 辦桌占路，通常整條路段封閉
    "廟會祭拜": 150,     # 祭拜人潮，路段半封閉
    "其他":      80,     # 其他人為管制（市集、拍攝等）
}

# ─────────────────────────────────────────────────────────────────────────────
# Layer 4：即時交通事件（layer4_accident.py）
# 資料來源：TDX /api/basic/v2/Road/Traffic/RealTimeEvent/City/Tainan
# ─────────────────────────────────────────────────────────────────────────────
LAYER4 = {
    1: ("車禍事故", 500),   # 強制迴避
    2: ("道路施工",  80),   # 施工仍可通行，輕度不偏好
    3: ("特殊事件", 200),   # 封路、活動管制
    4: ("天災",     500),   # 積水、崩塌，強制迴避
    5: ("其他異常", 100),   # 不明原因交通異常
}

# ─────────────────────────────────────────────────────────────────────────────
# Layer 5：觀光熱區時段懲罰（layer5_tourist.py）
# 資料來源：TDX 觀光署景點 API + 學術時段模型
# ─────────────────────────────────────────────────────────────────────────────
LAYER5 = {
    "temple": [
        {"day": "weekday", "hour_start":  9, "hour_end": 17, "penalty":  8},
        {"day": "weekend", "hour_start":  9, "hour_end": 18, "penalty": 20},
        {"day": "all",     "hour_start": 17, "hour_end": 21, "penalty": 12},
    ],
    "nightmarket": [
        {"day": "all",     "hour_start": 17, "hour_end": 23, "penalty": 25},
        {"day": "weekend", "hour_start": 12, "hour_end": 17, "penalty": 12},
        {"day": "weekday", "hour_start": 12, "hour_end": 17, "penalty":  5},
    ],
    "oldstreet": [
        {"day": "all",     "hour_start": 18, "hour_end": 23, "penalty": 20},
        {"day": "weekend", "hour_start": 14, "hour_end": 18, "penalty": 15},
        {"day": "weekday", "hour_start": 14, "hour_end": 18, "penalty":  8},
    ],
    "landmark": [
        {"day": "weekend", "hour_start": 10, "hour_end": 21, "penalty": 15},
        {"day": "weekday", "hour_start": 12, "hour_end": 18, "penalty":  6},
    ],
    "park": [
        {"day": "weekend", "hour_start":  8, "hour_end": 18, "penalty": 10},
        {"day": "weekday", "hour_start":  7, "hour_end":  9, "penalty":  5},
        {"day": "weekday", "hour_start": 17, "hour_end": 19, "penalty":  5},
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Layer 6：垃圾車清運時段避險（layer6_garbage.py）
# 資料來源：台南市環保局清潔車時刻表
# ─────────────────────────────────────────────────────────────────────────────
LAYER6 = {
    "garbage_blocked":  150,  # 單車道：垃圾車作業，後方完全堵死
    "garbage_passable":   1,  # 多車道：貨車可繞過垃圾車 → 不懲罰

    # 清運時段（若 API 無法取得，以此時段作為保底判斷）
    # 台南市一般清運時段：早班、晚班
    "default_schedule": [
        {"label": "早班", "hour_start":  7, "hour_end":  9},
        {"label": "晚班", "hour_start": 19, "hour_end": 21},
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# 靜態路網權重（load_base_graph，app.py）
# ─────────────────────────────────────────────────────────────────────────────
STATIC = {
    "narrow_road": 5,    # 窄巷 / 小路（living_street, alley, track, path）
                         # 原 ×70 過高，導致路由繞進更小的路
    "dead_end":    10,   # 死巷節點
                         # 原 ×100 過高，目的地在死巷時會無解
    # 單行道：不加懲罰（OSM 已限制逆向，懲罰反而讓路由走小路）
}

# ─────────────────────────────────────────────────────────────────────────────
# Layer 2：公車即時避險（layer2_bus.py）
# ─────────────────────────────────────────────────────────────────────────────
LAYER2 = {
    "bus_stop": 5,       # 有即時公車停靠的路段
                         # 輕度懲罰，非行駛時段自動跳過（不加懲罰）
}

# ─────────────────────────────────────────────────────────────────────────────
# Layer 3：廟會 / 人為管制（app.py → apply_event_risk）
# 資料來源：table_result.csv（台南市道路使用申請核准資料）
# ─────────────────────────────────────────────────────────────────────────────
LAYER3 = {
    "廟會宴客": 200,     # 辦桌占路，通常整條路段封閉
    "廟會祭拜": 150,     # 祭拜人潮，路段半封閉
    "其他":      80,     # 其他人為管制（市集、拍攝等）
}

# ─────────────────────────────────────────────────────────────────────────────
# Layer 4：即時交通事件（layer4_accident.py）
# 資料來源：TDX /api/basic/v2/Road/Traffic/RealTimeEvent/City/Tainan
# ─────────────────────────────────────────────────────────────────────────────
LAYER4 = {
    1: ("車禍事故", 500),   # 強制迴避
    2: ("道路施工",  80),   # 施工仍可通行，輕度不偏好
    3: ("特殊事件", 200),   # 封路、活動管制
    4: ("天災",     500),   # 積水、崩塌，強制迴避
    5: ("其他異常", 100),   # 不明原因交通異常
}

# ─────────────────────────────────────────────────────────────────────────────
# Layer 5：觀光熱區時段懲罰（layer5_tourist.py）
# 資料來源：TDX 觀光署景點 API + 學術時段模型
#
# 格式：{ 景點類型: [ {day, hour_start, hour_end, penalty}, ... ] }
#   day: "all" | "weekday"（週一~五）| "weekend"（週六~日）
#   penalty: 懲罰倍率
# ─────────────────────────────────────────────────────────────────────────────
LAYER5 = {
    "temple": [             # 廟宇、古蹟（赤崁樓、孔廟等）
        {"day": "weekday", "hour_start":  9, "hour_end": 17, "penalty":  8},
        {"day": "weekend", "hour_start":  9, "hour_end": 18, "penalty": 20},
        {"day": "all",     "hour_start": 17, "hour_end": 21, "penalty": 12},
    ],
    "nightmarket": [        # 夜市、美食街（國華街等）
        {"day": "all",     "hour_start": 17, "hour_end": 23, "penalty": 25},
        {"day": "weekend", "hour_start": 12, "hour_end": 17, "penalty": 12},
        {"day": "weekday", "hour_start": 12, "hour_end": 17, "penalty":  5},
    ],
    "oldstreet": [          # 老街、文青商圈（神農街、正興街、海安路）
        {"day": "all",     "hour_start": 18, "hour_end": 23, "penalty": 20},
        {"day": "weekend", "hour_start": 14, "hour_end": 18, "penalty": 15},
        {"day": "weekday", "hour_start": 14, "hour_end": 18, "penalty":  8},
    ],
    "landmark": [           # 地標商場（林百貨、新光三越等）
        {"day": "weekend", "hour_start": 10, "hour_end": 21, "penalty": 15},
        {"day": "weekday", "hour_start": 12, "hour_end": 18, "penalty":  6},
    ],
    "park": [               # 公園、廣場
        {"day": "weekend", "hour_start":  8, "hour_end": 18, "penalty": 10},
        {"day": "weekday", "hour_start":  7, "hour_end":  9, "penalty":  5},
        {"day": "weekday", "hour_start": 17, "hour_end": 19, "penalty":  5},
    ],
}