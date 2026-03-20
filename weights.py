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
LANE_BYPASS = {
    "bypass_multiplier": 1,
    "twoway_bypass_lanes": 4,
    "oneway_bypass_lanes": 2,
    "default_lanes": {
        "motorway":      6,
        "trunk":         4,
        "primary":       4,
        "secondary":     2,
        "tertiary":      2,
        "residential":   2,
        "service":       1,
        "living_street": 1,
        "alley":         1,
        "track":         1,
        "path":          1,
        "unclassified":  2,
    },
    "default_lanes_fallback": 2,
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
# Layer 4：即時交通事件（layer4_traffic.py）
# 資料來源：TDX /v2/Road/Traffic/Live/News/City/Tainan
# ─────────────────────────────────────────────────────────────────────────────
LAYER4 = {
    1: ("車禍事故", 500),   # 強制迴避
    2: ("道路施工",  80),   # 施工仍可通行，輕度不偏好
    3: ("特殊事件", 200),   # 封路、活動管制
    4: ("天災",     500),   # 積水、崩塌，強制迴避
    5: ("其他異常", 100),   # 不明原因交通異常
}

# ─────────────────────────────────────────────────────────────────────────────
# Layer 5：人類活動造成的通行不便（layer5_tourist.py）
# 涵蓋：觀光景點 / 學校上下學 / 傳統市場早市
# ─────────────────────────────────────────────────────────────────────────────

# 觀光景點時段懲罰
# 格式：{ 景點類型: [ {day, hour_start, hour_end, penalty}, ... ] }
#   day: "all" | "weekday"（週一~五）| "weekend"（週六~日）
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

# 學校上下學時段（週一~五）
# 黑貓早班配送（13:00前）與上學時段重疊，加重懲罰
# 格式：{ label: {hour_start, minute_start, hour_end, minute_end, penalty} }
LAYER5_SCHOOL = {
    "上學":       {"hour_start":  7, "minute_start": 20,
                   "hour_end":    8, "minute_end":   20, "penalty": 12000},
    "低年級放學": {"hour_start": 11, "minute_start": 20,
                   "hour_end":   12, "minute_end":   10, "penalty": 10000},
    "高年級放學": {"hour_start": 16, "minute_start":  0,
                   "hour_end":   16, "minute_end":   50, "penalty": 10000},
}

# 傳統市場早市時段（週一~六，週日多數休市）
LAYER5_MARKET = {
    "early_market": {"hour_start": 6, "hour_end": 10, "penalty": 8000},
}