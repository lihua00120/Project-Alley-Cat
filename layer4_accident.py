import requests
import xml.etree.ElementTree as ET
from weights import LAYER4

NS = "https://traffic.transportdata.tw/standard/traffic/schema/"


def apply_traffic_risk(G, client_id, client_secret):
    """
    Layer 4：即時道路事件（Live/News）
    - 無座標，不套地圖標記，不修改路網
    - 回傳：(G, markers, alerts)
        markers : 空清單（保持與其他 layer 介面一致）
        alerts  : 事件清單，供 app.py 顯示在頁面最上方
    """
    print("🚦 [Layer 4] 正在取得即時道路事件...")
    markers = []
    alerts  = []

    # 換 Token
    auth_url = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
    try:
        auth_res = requests.post(auth_url, data={
            'grant_type':    'client_credentials',
            'client_id':     client_id,
            'client_secret': client_secret,
        }, timeout=10)
        auth_res.raise_for_status()
        token = auth_res.json().get('access_token')
    except Exception as e:
        print(f"❌ [Layer 4] Token 取得失敗：{e}")
        return G, markers, alerts

    headers = {'authorization': f'Bearer {token}'}

    # 事件類型對應（對照 LAYER4 weights）
    kind_map = {
        '車禍':   (1, '🚨'),
        '事故':   (1, '🚨'),
        '火災':   (4, '🔥'),
        '施工':   (2, '🚧'),
        '封閉':   (3, '🚧'),
        '封路':   (3, '🚧'),
        '緊急救護': (4, '🚑'),
    }

    try:
        url = "https://tdx.transportdata.tw/api/basic/v2/Road/Traffic/Live/News/City/Tainan?$format=XML"
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        root = ET.fromstring(res.content)

        news_list = root.findall(f'.//{{{NS}}}News')
        print(f"  📡 Live/News 共 {len(news_list)} 筆")

        for news in news_list:
            title = news.findtext(f'{{{NS}}}Title',       '').strip()
            desc  = news.findtext(f'{{{NS}}}Description', '').strip()
            time  = news.findtext(f'{{{NS}}}PublishTime', '').strip()

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
                "icon":        icon,
                "kind":        matched_kind,
                "type_label":  type_label,
                "title":       title,
                "desc":        desc,
                "time":        time_str,
            })

        print(f"✅ [Layer 4] 共 {len(alerts)} 筆事件")

    except Exception as e:
        print(f"⚠️ [Layer 4] 資料抓取失敗：{e}")

    return G, markers, alerts