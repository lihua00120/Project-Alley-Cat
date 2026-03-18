import streamlit as st
import osmnx as ox
import os
import networkx as nx
import folium
import requests
import pandas as pd
from datetime import datetime, date
from dotenv import load_dotenv
import streamlit.components.v1 as components

from layer2_bus import apply_bus_risk

load_dotenv()

TDX_CLIENT_ID     = os.getenv("TDX_CLIENT_ID")
TDX_CLIENT_SECRET = os.getenv("TDX_CLIENT_SECRET")
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY")

st.set_page_config(page_title="Project Alley-Cat", layout="wide")
st.title("🐈 Project Alley-Cat：避險雷達")

# ── 讀取 CSV ──────────────────────────────────────────────────────────────────
@st.cache_data
def load_event_data():
    try:
        df = pd.read_csv("table_result.csv", encoding="utf-8-sig")
    except FileNotFoundError:
        return pd.DataFrame()

    def parse_dates(s):
        try:
            s = str(s).strip()
            parts = s.split("~")
            start = pd.to_datetime(parts[0].strip(), format="%Y/%m/%d %H:%M")
            end   = pd.to_datetime(parts[1].strip(), format="%Y/%m/%d %H:%M")
            return start, end
        except Exception:
            return None, None

    df[['start_dt', 'end_dt']] = df['使用日期'].apply(
        lambda x: pd.Series(parse_dates(x))
    )
    return df

event_df = load_event_data()

def get_active_events(selected_date: date, df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    sel  = pd.Timestamp(selected_date)
    mask = (df['start_dt'].notna()) & (df['end_dt'].notna()) & \
           (df['start_dt'].dt.normalize() <= sel) & \
           (df['end_dt'].dt.normalize()   >= sel)
    return df[mask].reset_index(drop=True)

# ── 路網載入 ──────────────────────────────────────────────────────────────────
@st.cache_resource
def load_base_graph():
    G = ox.graph_from_place("中西區, 台南市, 台灣", network_type='drive')
    dead_end_nodes = {node for node, deg in G.degree() if deg == 1}
    narrow_types   = {'service', 'living_street', 'alley', 'track', 'path'}

    for u, v, k, data in G.edges(keys=True, data=True):
        length  = data.get('length', 1.0)
        cost    = length
        highway = data.get('highway', '')
        if isinstance(highway, list):
            highway = highway[0]
        if highway in narrow_types:
            cost *= 70
        if u in dead_end_nodes or v in dead_end_nodes:
            cost *= 100
        data['dynamic_cost'] = cost
    return G

with st.spinner("🌍 正在載入並計算避險路網權重..."):
    G_base = load_base_graph()

# ── Google Geocoding ──────────────────────────────────────────────────────────
def get_precise_location(address: str, api_key: str):
    url  = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={api_key}&language=zh-TW"
    resp = requests.get(url).json()
    if resp['status'] == 'OK':
        loc = resp['results'][0]['geometry']['location']
        return loc['lat'], loc['lng']
    raise ValueError(f"Google 找不到這個地址：{address}")

# ── CSV 管制路段套用權重 ───────────────────────────────────────────────────────
def apply_event_risk(G, active_events: pd.DataFrame, api_key: str):
    PENALTY = {'廟會宴客': 200, '廟會祭拜': 200}
    DEFAULT_PENALTY = 30
    if active_events.empty:
        return G
    for _, row in active_events.iterrows():
        road_str   = str(row.get('核准路段', ''))
        event_type = str(row.get('申請種類', ''))
        penalty    = PENALTY.get(event_type, DEFAULT_PENALTY)
        try:
            lat, lon = get_precise_location(road_str, api_key)
            node = ox.distance.nearest_nodes(G, X=lon, Y=lat)
            for u, v, k, d in G.edges(keys=True, data=True):
                if u == node or v == node:
                    d['dynamic_cost'] = d.get('dynamic_cost', 1.0) * penalty
        except Exception:
            pass
    return G

# ── 多目的地貪婪最近鄰路線 ───────────────────────────────────────────────────
def plan_multi_stop_route(G, orig_node: int, dest_nodes: list) -> list:
    remaining = dest_nodes.copy()
    full_path = []
    current   = orig_node
    order     = []

    while remaining:
        best_node, best_cost, best_path = None, float('inf'), []
        for candidate in remaining:
            try:
                cost = nx.shortest_path_length(G, current, candidate, weight='dynamic_cost')
                if cost < best_cost:
                    best_cost = cost
                    best_node = candidate
                    best_path = nx.shortest_path(G, current, candidate, weight='dynamic_cost')
            except nx.NetworkXNoPath:
                continue
        if best_node is None:
            st.warning("⚠️ 部分目的地無法到達，已自動略過")
            break
        full_path += best_path[1:] if full_path else best_path
        order.append(best_node)
        current = best_node
        remaining.remove(best_node)

    return full_path, order

# ── 側邊欄 UI ─────────────────────────────────────────────────────────────────
st.sidebar.header("🕹️ 導航控制")

# 日期選擇
st.sidebar.subheader("📅 配送日期")
selected_date = st.sidebar.date_input("選擇配送日期", value=date.today())
active_events = get_active_events(selected_date, event_df)

if not active_events.empty:
    st.sidebar.warning(f"⚠️ 當天有 **{len(active_events)}** 筆道路管制事件")
    with st.sidebar.expander("查看管制清單"):
        for _, row in active_events.iterrows():
            st.markdown(f"- **{row.get('申請種類','')}**｜{row.get('核准路段','')}")
else:
    st.sidebar.success("✅ 當天無道路管制事件")

st.sidebar.divider()

# 起點
st.sidebar.subheader("📍 起點")
start_loc = st.sidebar.text_input("出發地址", value="臺南市中西區樹林街二段33號")

st.sidebar.divider()

# 多目的地
st.sidebar.subheader("🏁 目的地（可多個）")
if "destinations" not in st.session_state:
    st.session_state.destinations = ["臺南市中西區神農街135號"]

for i in range(len(st.session_state.destinations)):
    col_input, col_del = st.sidebar.columns([4, 1])
    with col_input:
        st.session_state.destinations[i] = st.text_input(
            f"目的地 {i+1}",
            value=st.session_state.destinations[i],
            key=f"dest_{i}"
        )
    with col_del:
        st.write("")
        if st.button("✕", key=f"del_{i}") and len(st.session_state.destinations) > 1:
            st.session_state.destinations.pop(i)
            st.rerun()

if st.sidebar.button("＋ 新增目的地", use_container_width=True):
    st.session_state.destinations.append("")
    st.rerun()

st.sidebar.divider()

activate_bus    = st.sidebar.checkbox("🚌 啟用公車動態避險", value=True)
activate_events = st.sidebar.checkbox("🎪 啟用廟會 / 活動避險", value=True)

with st.sidebar.expander("ℹ️ 權重規則說明"):
    st.markdown("""
| 情境 | 倍率 |
|------|------|
| 一般道路 | ×1 |
| 公車站附近 | ×5 |
| 單行道 | ×50 |
| 窄巷 / service | ×70 |
| 活動（其他）| ×30 |
| 死巷節點 | ×100 |
| 廟會宴客 / 祭拜 | ×200 |
    """)

# ── 導航執行 ──────────────────────────────────────────────────────────────────
if st.sidebar.button("🚀 開始導航", type="primary", use_container_width=True):
    valid_dests = [d.strip() for d in st.session_state.destinations if d.strip()]
    if not valid_dests:
        st.error("請至少輸入一個目的地！")
        st.stop()

    with st.spinner("正在計算最佳多站路徑..."):
        try:
            G_run = G_base.copy()

            if activate_bus and TDX_CLIENT_ID and TDX_CLIENT_SECRET:
                G_run = apply_bus_risk(G_run, TDX_CLIENT_ID, TDX_CLIENT_SECRET)

            if activate_events and not active_events.empty:
                G_run = apply_event_risk(G_run, active_events, GOOGLE_API_KEY)

            start_lat, start_lon = get_precise_location(start_loc, GOOGLE_API_KEY)
            orig = ox.distance.nearest_nodes(G_run, X=start_lon, Y=start_lat)

            dest_coords, dest_nodes = [], []
            for addr in valid_dests:
                lat, lon = get_precise_location(addr, GOOGLE_API_KEY)
                dest_coords.append((lat, lon, addr))
                dest_nodes.append(ox.distance.nearest_nodes(G_run, X=lon, Y=lat))

            full_route, ordered_nodes = plan_multi_stop_route(G_run, orig, dest_nodes)

            if not full_route:
                st.error("❌ 無法規劃路線")
                st.stop()

            raw_length = sum(
                G_run[u][v][0].get('length', 0)
                for u, v in zip(full_route[:-1], full_route[1:])
            )
            col1, col2, col3 = st.columns(3)
            col1.metric("🛣️ 總路徑長度", f"{raw_length/1000:.2f} km")
            col2.metric("🏁 目的地數量", f"{len(valid_dests)} 站")
            col3.metric("🎪 管制路段數", f"{len(active_events)} 筆")

            # 地圖
            m = folium.Map(
                location=[start_lat, start_lon], zoom_start=15,
                tiles='http://mt0.google.com/vt/lyrs=m&hl=zh-TW&x={x}&y={y}&z={z}',
                attr='Google Maps'
            )

            route_coords = [[G_run.nodes[n]['y'], G_run.nodes[n]['x']] for n in full_route]
            folium.PolyLine(route_coords, color="#00E676", weight=6, opacity=0.85,
                            tooltip="避險最佳路徑").add_to(m)

            folium.Marker(
                [G_run.nodes[orig]['y'], G_run.nodes[orig]['x']],
                popup=f"🚚 出發點：{start_loc}",
                icon=folium.Icon(color='green', icon='truck', prefix='fa')
            ).add_to(m)

            colors = ['red','blue','purple','orange','darkred','cadetblue','darkblue','pink']
            # 依照實際配送順序（ordered_nodes）對應到 dest_coords
            node_to_coord = {ox.distance.nearest_nodes(G_run, X=lon, Y=lat): (lat, lon, addr)
                             for lat, lon, addr in dest_coords}

            for idx, node in enumerate(ordered_nodes):
                lat, lon, addr = node_to_coord.get(node, dest_coords[idx])
                truck_lat = G_run.nodes[node]['y']
                truck_lon = G_run.nodes[node]['x']
                color     = colors[idx % len(colors)]

                folium.Marker([truck_lat, truck_lon],
                    popup=f"🚚 第 {idx+1} 站停靠點",
                    icon=folium.Icon(color=color, icon='truck', prefix='fa')).add_to(m)
                folium.Marker([lat, lon],
                    popup=f"📦 第 {idx+1} 站：{addr}",
                    icon=folium.Icon(color=color, icon='home', prefix='fa')).add_to(m)
                folium.PolyLine([[truck_lat, truck_lon],[lat, lon]],
                    color="gray", weight=2, dash_array='5,5').add_to(m)
                folium.Marker([lat, lon], icon=folium.DivIcon(
                    html=f'<div style="font-size:13px;font-weight:bold;background:#fff;'
                         f'border-radius:50%;width:22px;height:22px;line-height:22px;'
                         f'text-align:center;border:2px solid #333">{idx+1}</div>',
                    icon_size=(22,22), icon_anchor=(11,11))).add_to(m)

            if activate_events and not active_events.empty:
                for _, row in active_events.iterrows():
                    try:
                        lat, lon = get_precise_location(str(row['核准路段']), GOOGLE_API_KEY)
                        folium.CircleMarker([lat, lon], radius=10,
                            color='red', fill=True, fill_opacity=0.4,
                            popup=f"🎪 {row.get('申請種類','')}｜{row.get('核准路段','')}"
                        ).add_to(m)
                    except Exception:
                        pass

            m.fit_bounds(route_coords)
            components.html(m._repr_html_(), height=620)

            st.subheader("📋 建議配送順序")
            order_data = []
            for idx, node in enumerate(ordered_nodes):
                lat, lon, addr = node_to_coord.get(node, dest_coords[idx])
                order_data.append({"順序": f"第 {idx+1} 站", "地址": addr})
            st.table(pd.DataFrame(order_data))

        except nx.NetworkXNoPath:
            st.error("❌ 找不到可行路徑，請確認地址是否在中西區範圍內。")
        except Exception as e:
            st.error(f"❌ 錯誤：{e}")