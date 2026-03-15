import streamlit as st
import osmnx as ox
import networkx as nx
import folium
from streamlit_folium import st_folium

# 1. 網頁標題與設定
st.set_page_config(page_title="Project Alley-Cat", layout="wide")
st.title("🐈 Project Alley-Cat：台南中西區微觀避險雷達")
st.markdown("這是一個結合圖論與即時動態的物流避險系統，能自動避開大客車與擁擠巷弄。")

# 2. 核心大腦：快取路網資料 (避免每次重整網頁都要重新下載)
@st.cache_resource
def load_graph():
    place_name = "中西區, 台南市, 台灣"
    # 下載地圖
    G = ox.graph_from_place(place_name, network_type='drive')

    # 加入路寬分級懲罰 (第一層物理阻力)
    hierarchy_penalty = {'primary': 1, 'secondary': 1.2, 'tertiary': 2, 'residential': 5, 'service': 10, 'unclassified': 3}
    for u, v, k, data in G.edges(keys=True, data=True):
        h_type = data.get('highway')
        if isinstance(h_type, list): h_type = h_type[0]
        data['dynamic_cost'] = data['length'] * hierarchy_penalty.get(h_type, 2)

    return G

# 載入地圖模型
with st.spinner("正在載入中西區路網模型..."):
    G = load_graph()

# 3. 側邊欄控制面板
st.sidebar.header("🕹️ 導航控制中心")
st.sidebar.markdown("請設定起始點與終點：")
# 為了測試方便，我們先預設好剛剛成功繞道的座標
start_lat = st.sidebar.number_input("起點緯度", value=23.0001, format="%.4f")
start_lon = st.sidebar.number_input("起點經度", value=120.1969, format="%.4f")
end_lat = st.sidebar.number_input("終點緯度", value=22.9960, format="%.4f")
end_lon = st.sidebar.number_input("終點經度", value=120.1950, format="%.4f")

activate_risk = st.sidebar.checkbox("🚨 模擬突發事件：神農街有公車停靠", value=True)

# 4. 運算路徑
orig = ox.distance.nearest_nodes(G, X=start_lon, Y=start_lat)
dest = ox.distance.nearest_nodes(G, X=end_lon, Y=end_lat)

# 如果勾選了突發事件，就把神農街附近的路口加上巨大阻力
risk_node = ox.distance.nearest_nodes(G, X=120.1970, Y=22.9985) # 神農街概略位置
if activate_risk:
    for u, v, k, data in G.edges(keys=True, data=True):
        if u == risk_node or v == risk_node:
            data['dynamic_cost'] += 10000

# 計算兩條路線
route_trad = nx.shortest_path(G, orig, dest, weight='length')
route_safe = nx.shortest_path(G, orig, dest, weight='dynamic_cost')

# 5. 繪製互動式地圖
m = folium.Map(location=[22.998, 120.196], zoom_start=15, tiles="CartoDB positron")

# 將傳統路徑 (紅色) 畫上地圖
trad_coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in route_trad]
folium.PolyLine(trad_coords, color="red", weight=4, opacity=0.6, tooltip="傳統最短路徑").add_to(m)

# 將避險路徑 (綠色) 畫上地圖
safe_coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in route_safe]
folium.PolyLine(safe_coords, color="lime", weight=6, opacity=0.9, tooltip="Alley-Cat 避險路徑").add_to(m)

# 標記起終點和風險點
folium.Marker([start_lat, start_lon], popup="起點", icon=folium.Icon(color="blue")).add_to(m)
folium.Marker([end_lat, end_lon], popup="終點", icon=folium.Icon(color="green")).add_to(m)
if activate_risk:
    folium.CircleMarker([G.nodes[risk_node]['y'], G.nodes[risk_node]['x']], radius=10, color="orange", fill=True, fill_color="orange", popup="⚠️ 風險區").add_to(m)

# 在網頁上顯示地圖
st_folium(m, width=800, height=600)
