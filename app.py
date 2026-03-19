import streamlit as st
import osmnx as ox
import os
import networkx as nx
import folium
import requests
import pandas as pd
from datetime import date
from dotenv import load_dotenv
import streamlit.components.v1 as components
import itertools

from layer2_bus      import apply_bus_risk
from layer4_accident import apply_traffic_risk
from layer5_tourist  import apply_tourist_risk
from layer6_garbage  import apply_garbage_risk
from weights         import STATIC, LAYER3

load_dotenv()
TDX_CLIENT_ID     = os.getenv("TDX_CLIENT_ID")
TDX_CLIENT_SECRET = os.getenv("TDX_CLIENT_SECRET")
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY")

# ─────────────────────────────────────────────────────────────────────────────
# 頁面設定
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Project Alley-Cat", layout="wide")

# ── 右上角：日期選擇 + 標題（用欄位排版）────────────────────────────────────
col_title, col_date = st.columns([3, 1])
with col_title:
    st.title("🐈 Project Alley-Cat：避險雷達")
with col_date:
    st.write("")   # 推到同高
    selected_date = st.date_input(
        "📅 配送日期",
        value=date.today(),
        min_value=date(2026, 1, 1),
        max_value=date(2027, 12, 31),
        label_visibility="visible",
    )

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# CSV 載入（Layer 3 人為管制事件）
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data
def load_event_csv():
    for enc in ["utf-8-sig", "cp950", "utf-8"]:
        try:
            df = pd.read_csv("table_result.csv", encoding=enc)
            break
        except Exception:
            df = pd.DataFrame()

    if df.empty:
        return df

    def parse_dt(s, part):
        try:
            return pd.to_datetime(str(s).split("~")[part].strip(), format="%Y/%m/%d %H:%M")
        except Exception:
            return pd.NaT

    df["開始時間"] = df["使用日期"].apply(lambda s: parse_dt(s, 0))
    df["結束時間"] = df["使用日期"].apply(lambda s: parse_dt(s, 1))
    return df

event_df = load_event_csv()

# ─────────────────────────────────────────────────────────────────────────────
# 路網載入 + 靜態權重
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource
def load_base_graph():
    G = ox.graph_from_place("中西區, 台南市, 台灣", network_type='drive')
    dead_end_nodes = {n for n, deg in G.degree() if deg == 1}
    narrow_types   = {'living_street', 'alley', 'track', 'path'}

    for u, v, k, data in G.edges(keys=True, data=True):
        cost    = data.get('length', 1.0)
        highway = data.get('highway', '')
        if isinstance(highway, list):
            highway = highway[0]
        if highway in narrow_types:
            cost *= STATIC["narrow_road"]
        if u in dead_end_nodes or v in dead_end_nodes:
            cost *= STATIC["dead_end"]
        data['dynamic_cost'] = cost
    return G

with st.spinner("🌍 正在載入並計算避險路網權重..."):
    G_base = load_base_graph()

# ─────────────────────────────────────────────────────────────────────────────
# Google Geocoding
# ─────────────────────────────────────────────────────────────────────────────
def get_location(address: str):
    url  = (f"https://maps.googleapis.com/maps/api/geocode/json"
            f"?address={address}&key={GOOGLE_API_KEY}&language=zh-TW")
    resp = requests.get(url).json()
    if resp['status'] == 'OK':
        loc = resp['results'][0]['geometry']['location']
        return loc['lat'], loc['lng']
    raise ValueError(f"找不到地址：{address}")

# ─────────────────────────────────────────────────────────────────────────────
# Layer 3：CSV 人為管制事件
# ─────────────────────────────────────────────────────────────────────────────
def apply_event_risk(G, sel_date: date):
    if event_df.empty:
        return G, []

    active = event_df[
        event_df["開始時間"].notna() &
        event_df["結束時間"].notna() &
        (event_df["開始時間"].dt.date <= sel_date) &
        (event_df["結束時間"].dt.date  >= sel_date)
    ]
    if active.empty:
        return G, []

    penalty_map = LAYER3
    markers = []

    for _, row in active.iterrows():
        addr    = str(row.get("核准路段", "")).strip()
        kind    = str(row.get("申請種類", "其他")).strip()
        penalty = penalty_map.get(kind, 80)
        if not addr or addr == "nan":
            continue
        try:
            lat, lon = get_location(addr)
            node     = ox.distance.nearest_nodes(G, X=lon, Y=lat)
            for u, v, k, d in G.edges(keys=True, data=True):
                if u == node or v == node:
                    d['dynamic_cost'] = d.get('dynamic_cost', 1.0) * penalty
            markers.append({
                "lat": lat, "lon": lon, "addr": addr, "kind": kind,
                "start": row["開始時間"].strftime("%m/%d %H:%M"),
                "end":   row["結束時間"].strftime("%m/%d %H:%M"),
                "layer": "event",
            })
        except Exception:
            continue

    return G, markers

# ─────────────────────────────────────────────────────────────────────────────
# 貪婪多目的地路線（TSP 近似）
# ─────────────────────────────────────────────────────────────────────────────
def greedy_route(G, orig, dest_nodes):
    remaining, current, order, segments = list(dest_nodes), orig, [], []
    while remaining:
        best_node, best_cost, best_path = None, float('inf'), []
        for cand in remaining:
            try:
                c = nx.shortest_path_length(G, current, cand, weight='dynamic_cost')
                if c < best_cost:
                    best_cost = c
                    best_node = cand
                    best_path = nx.shortest_path(G, current, cand, weight='dynamic_cost')
            except nx.NetworkXNoPath:
                continue
        if best_node is None:
            st.warning("⚠️ 部分目的地無法到達，已自動略過")
            break
        order.append(best_node)
        segments.append(best_path)
        remaining.remove(best_node)
        current = best_node
    return order, segments

# ─────────────────────────────────────────────────────────────────────────────
# 側邊欄 UI（精簡版，移除開發者資訊）
# ─────────────────────────────────────────────────────────────────────────────
st.sidebar.header("🕹️ 導航控制")

# ── 當天管制事件提示（只顯示數量，不顯示詳細清單）──────────────────────────
active_preview = event_df[
    event_df["開始時間"].notna() &
    event_df["結束時間"].notna() &
    (event_df["開始時間"].dt.date <= selected_date) &
    (event_df["結束時間"].dt.date  >= selected_date)
] if not event_df.empty else pd.DataFrame()

if not active_preview.empty:
    st.sidebar.warning(f"⚠️ 當天有 **{len(active_preview)}** 筆道路管制（廟會 / 活動）")
else:
    st.sidebar.success("✅ 當天無道路管制事件")

# 展開才看到詳細（給司機查用）
with st.sidebar.expander("📋 查看當天管制詳情"):
    if active_preview.empty:
        st.write("無管制事件")
    else:
        icon_map = {"廟會宴客": "🏮", "廟會祭拜": "🙏", "其他": "⚠️"}
        for _, r in active_preview.iterrows():
            icon = icon_map.get(str(r.get("申請種類","")).strip(), "⚠️")
            st.markdown(
                f"{icon} **{r.get('申請種類','')}**  \n"
                f"📍 {r.get('核准路段','')}  \n"
                f"🕐 {r.get('使用日期','')}"
            )
            st.divider()

st.sidebar.markdown("---")

# ── 起點 ──────────────────────────────────────────────────────────────────────
start_loc = st.sidebar.text_input("📍 起點", value="臺南市中西區樹林街二段33號")

# ── 多目的地 ───────────────────────────────────────────────────────────────────
st.sidebar.markdown("**🏁 目的地清單**（可新增多個）")
if "destinations" not in st.session_state:
    st.session_state.destinations = ["臺南市中西區神農街135號"]

for i in range(len(st.session_state.destinations)):
    cols = st.sidebar.columns([5, 1])
    st.session_state.destinations[i] = cols[0].text_input(
        f"目的地 {i+1}", value=st.session_state.destinations[i],
        key=f"dest_{i}", label_visibility="collapsed"
    )
    if cols[1].button("✕", key=f"del_{i}"):
        st.session_state.destinations.pop(i)
        st.rerun()

if st.sidebar.button("➕ 新增目的地", use_container_width=True):
    st.session_state.destinations.append("")
    st.rerun()

st.sidebar.markdown("---")

# ── 避險層開關（只保留對司機有意義的開關）──────────────────────────────────
st.sidebar.markdown("**🛡️ 避險選項**")
activate_bus      = st.sidebar.checkbox("🚌 公車動態避險",   value=True)
activate_events   = st.sidebar.checkbox("🎪 廟會 / 活動避險", value=True)
activate_accident = st.sidebar.checkbox("🚨 即時車禍避險",   value=True)
activate_tourist  = st.sidebar.checkbox("📸 觀光熱區避險",   value=True)
activate_garbage  = st.sidebar.checkbox("🗑️ 垃圾車清運避險", value=True)

st.sidebar.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# 導航執行
# ─────────────────────────────────────────────────────────────────────────────
ROUTE_COLORS = ["#00E676", "#FF6D00", "#2979FF", "#D500F9", "#FFEA00", "#00BCD4"]
STOP_COLORS  = ['red', 'orange', 'purple', 'darkred', 'cadetblue']
EVENT_ICONS  = {"廟會宴客": "🏮", "廟會祭拜": "🙏", "其他": "⚠️"}
TYPE_LABELS  = {"temple": "廟宇古蹟", "nightmarket": "夜市美食",
                "oldstreet": "老街商圈", "landmark": "地標商場", "park": "公園廣場"}

if st.sidebar.button("🚀 開始導航", type="primary", use_container_width=True):

    valid_dests = [d.strip() for d in st.session_state.destinations if d.strip()]
    if not valid_dests:
        st.error("請至少輸入一個目的地！")
        st.stop()

    all_markers = []

    with st.spinner("正在計算最佳多點避險路徑..."):
        try:
            G_run = G_base.copy()

            # Layer 2：公車即時
            if activate_bus:
                if TDX_CLIENT_ID and TDX_CLIENT_SECRET:
                    G_run = apply_bus_risk(G_run, TDX_CLIENT_ID, TDX_CLIENT_SECRET)
                else:
                    st.warning("⚠️ 未設定 TDX 金鑰，跳過公車避險")

            # Layer 3：人為管制
            if activate_events:
                G_run, ev_markers = apply_event_risk(G_run, selected_date)
                all_markers.extend(ev_markers)

            # Layer 4：即時車禍
            if activate_accident:
                if TDX_CLIENT_ID and TDX_CLIENT_SECRET:
                    G_run, acc_markers = apply_traffic_risk(G_run, TDX_CLIENT_ID, TDX_CLIENT_SECRET)
                    all_markers.extend(acc_markers)
                else:
                    st.warning("⚠️ 未設定 TDX 金鑰，跳過車禍避險")

            # Layer 5：觀光熱區（TDX 官方景點 + 時段模型）
            if activate_tourist:
                G_run, tour_markers, tour_summary = apply_tourist_risk(
                    G_run, TDX_CLIENT_ID, TDX_CLIENT_SECRET
                )
                all_markers.extend(tour_markers)

            # Layer 6：垃圾車清運避險
            if activate_garbage:
                G_run, garbage_markers, garbage_active, garbage_label = apply_garbage_risk(G_run)
                all_markers.extend(garbage_markers)
                if garbage_active:
                    st.warning(f"🗑️ Layer 6：{garbage_label}清運時段（含誤點緩衝），{len(garbage_markers)} 個路段已套用避險")

            # 地理編碼
            s_lat, s_lon = get_location(start_loc)
            orig = ox.distance.nearest_nodes(G_run, X=s_lon, Y=s_lat)

            dest_info = []
            for addr in valid_dests:
                try:
                    lat, lon = get_location(addr)
                    node     = ox.distance.nearest_nodes(G_run, X=lon, Y=lat)
                    dest_info.append({"addr": addr, "lat": lat, "lon": lon, "node": node})
                except Exception as e:
                    st.warning(f"⚠️ 無法解析「{addr}」：{e}")

            if not dest_info:
                st.error("所有目的地均無法解析，請檢查地址。")
                st.stop()

            # 多目的地路線
            ordered_nodes, segments = greedy_route(G_run, orig, [d["node"] for d in dest_info])

            # ── 統計指標 ───────────────────────────────────────────────────────
            total_len  = sum(G_run[u][v][0].get('length', 0) for s in segments for u, v in zip(s[:-1], s[1:]))
            acc_count      = sum(1 for m in all_markers if m.get("layer") == "accident")
            ev_count       = sum(1 for m in all_markers if m.get("layer") == "event")
            tour_count     = sum(1 for m in all_markers if m.get("layer") == "tourist")
            garbage_count  = sum(1 for m in all_markers if m.get("layer") == "garbage")

            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("🛣️ 總路徑長度", f"{total_len/1000:.2f} km")
            c2.metric("📦 配送站數",   f"{len(ordered_nodes)}")
            c3.metric("🚨 即時事故",   f"{acc_count} 筆")
            c4.metric("🎪 道路管制",   f"{ev_count} 筆")
            c5.metric("📸 觀光熱區",   f"{tour_count} 個")
            c6.metric("🗑️ 垃圾清運",   f"{garbage_count} 路段")

            # Layer 5 摘要（給司機看，有數據來源說明）
            if activate_tourist:
                st.info(f"📸 觀光熱區資訊：{tour_summary}（資料來源：TDX 交通部觀光署）")

            # ── 送貨順序表 ─────────────────────────────────────────────────────
            st.subheader("📋 建議配送順序")
            rows = []
            for rank, node in enumerate(ordered_nodes):
                info    = next((d for d in dest_info if d["node"] == node), None)
                seg     = segments[rank]
                seg_len = sum(G_run[u][v][0].get('length', 0) for u, v in zip(seg[:-1], seg[1:]))
                rows.append({
                    "順序":   f"第 {rank+1} 站",
                    "地址":   info["addr"] if info else "未知",
                    "段距離": f"{seg_len/1000:.2f} km",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # ── 地圖 ───────────────────────────────────────────────────────────
            m = folium.Map(
                location=[s_lat, s_lon], zoom_start=15,
                tiles='http://mt0.google.com/vt/lyrs=m&hl=zh-TW&x={x}&y={y}&z={z}',
                attr='Google Maps'
            )

            all_coords = []
            for idx, (seg, color) in enumerate(zip(segments, itertools.cycle(ROUTE_COLORS))):
                coords  = [[G_run.nodes[n]['y'], G_run.nodes[n]['x']] for n in seg]
                seg_len = sum(G_run[u][v][0].get('length', 0) for u, v in zip(seg[:-1], seg[1:]))
                all_coords.extend(coords)
                folium.PolyLine(
                    coords, color=color, weight=6, opacity=0.85,
                    tooltip=f"第 {idx+1} 段（{seg_len/1000:.2f} km）"
                ).add_to(m)

            # 起點
            folium.Marker(
                [G_run.nodes[orig]['y'], G_run.nodes[orig]['x']],
                popup=f"🚚 出發點：{start_loc}",
                icon=folium.Icon(color='green', icon='truck', prefix='fa')
            ).add_to(m)

            # 各目的地
            for rank, node in enumerate(ordered_nodes):
                info  = next((d for d in dest_info if d["node"] == node), None)
                color = STOP_COLORS[rank % len(STOP_COLORS)]
                n_lat = G_run.nodes[node]['y']
                n_lon = G_run.nodes[node]['x']

                folium.Marker(
                    [n_lat, n_lon],
                    popup=f"🚚 第 {rank+1} 站停靠點",
                    icon=folium.Icon(color=color, icon='truck', prefix='fa')
                ).add_to(m)
                if info:
                    folium.Marker(
                        [info["lat"], info["lon"]],
                        popup=f"📦 第 {rank+1} 站：{info['addr']}",
                        icon=folium.Icon(color='blue', icon='home', prefix='fa')
                    ).add_to(m)
                    folium.PolyLine(
                        [[n_lat, n_lon], [info["lat"], info["lon"]]],
                        color="gray", weight=2, dash_array='5,5',
                        tooltip="推車步行路線"
                    ).add_to(m)
                    folium.Marker(
                        [info["lat"], info["lon"]],
                        icon=folium.DivIcon(html=(
                            f'<div style="background:#1a1a2e;color:white;border-radius:50%;'
                            f'width:22px;height:22px;text-align:center;line-height:22px;'
                            f'font-weight:bold;font-size:12px;border:2px solid {color}">'
                            f'{rank+1}</div>'
                        ))
                    ).add_to(m)

            # 額外標記
            for mk in all_markers:
                layer = mk.get("layer")

                if layer == "event":
                    folium.CircleMarker(
                        location=[mk["lat"], mk["lon"]],
                        radius=10, color="#FF3355",
                        fill=True, fill_color="#FF3355", fill_opacity=0.55,
                        popup=(
                            f"{EVENT_ICONS.get(mk['kind'],'⚠️')} {mk['kind']}<br>"
                            f"📍 {mk['addr']}<br>"
                            f"🕐 {mk['start']} ～ {mk['end']}"
                        ),
                        tooltip=f"🎪 {mk['kind']}"
                    ).add_to(m)

                elif layer == "accident":
                    # 依事件類型決定顏色
                    acc_color = {1: 'red', 2: 'gray', 3: 'orange', 4: 'darkred', 5: 'orange'
                                 }.get(mk.get("type_code", 5), 'orange')
                    folium.Marker(
                        location=[mk["lat"], mk["lon"]],
                        popup=(
                            f"🚨 <b>{mk['type']}</b><br>"
                            f"說明：{mk['desc'] or '（無詳細說明）'}<br>"
                            f"路徑懲罰：×{mk.get('penalty', 100)}"
                        ),
                        tooltip=f"🚨 {mk['type']}",
                        icon=folium.Icon(color=acc_color, icon='exclamation-triangle', prefix='fa')
                    ).add_to(m)

                elif layer == "tourist":
                    penalty_label = (
                        "高峰" if mk["penalty"] >= 15 else
                        "中峰" if mk["penalty"] >= 8  else "低峰"
                    )
                    src_label = "TDX官方" if mk.get("source") == "TDX" else "內建"
                    folium.Marker(
                        location=[mk["lat"], mk["lon"]],
                        popup=(
                            f"📸 <b>{mk['name']}</b>（{TYPE_LABELS.get(mk['type'], mk['type'])}）<br>"
                            f"目前人潮：{penalty_label}（懲罰 ×{mk['penalty']}）<br>"
                            f"資料來源：{src_label}"
                        ),
                        tooltip=f"📸 {mk['name']}（{penalty_label}）",
                        icon=folium.Icon(color='purple', icon='camera', prefix='fa')
                    ).add_to(m)

                elif layer == "garbage":
                    folium.Marker(
                        location=[mk["lat"], mk["lon"]],
                        popup=(
                            f"🗑️ <b>垃圾車清運中</b><br>"
                            f"區域：{mk.get('area', '')}<br>"
                            f"班次：{mk.get('time_label', '')}<br>"
                            f"單車道路段已套用避險懲罰"
                        ),
                        tooltip=f"🗑️ 垃圾車清運（{mk.get('area', '')}）",
                        icon=folium.Icon(color='darkgreen', icon='trash', prefix='fa')
                    ).add_to(m)

            if all_coords:
                m.fit_bounds(all_coords)

            components.html(m._repr_html_(), height=650)

        except nx.NetworkXNoPath:
            st.error("❌ 找不到可行路徑，請確認地址是否在中西區範圍內。")
        except Exception as e:
            st.error(f"❌ 錯誤：{e}")