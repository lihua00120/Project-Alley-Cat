import streamlit as st
import osmnx as ox
import os
import networkx as nx
import folium
from streamlit_folium import st_folium
import requests
from dotenv import load_dotenv

# 引入layer1、layer2、layer3零件
from layer2_bus import get_bus_data_v3

load_dotenv()
# 從 .env 讀取憑證
TDX_CLIENT_ID = os.getenv("TDX_CLIENT_ID")
TDX_CLIENT_SECRET = os.getenv("TDX_CLIENT_SECRET")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# 1. 網頁標題
st.set_page_config(page_title="Project Alley-Cat", layout="wide")
st.title("🐈 Project Alley-Cat：避險雷達")

# 2. 載入地圖
@st.cache_resource
def load_base_graph():
    place_name = "中西區, 台南市, 台灣"

    # 抓取可行駛路網 (drive)
    # ox.graph_from_place 會自動抓取單行道 (oneway) 等屬性
    G = ox.graph_from_place(place_name, network_type='drive')

    # 判斷死巷節點 (節點連接數為 1)
    dead_end_nodes = set([node for node, degree in G.degree() if degree == 1])

    # 定義窄巷類型
    narrow_types = ['service', 'living_street', 'alley']

    for u, v, k, data in G.edges(keys=True, data=True):
        # 取得基本長度 (公尺)
        length = data.get('length', 1.0)
        cost = length

        # 1. 處理道路類型標籤 (有些標籤是 list)
        highway = data.get('highway', '')
        if isinstance(highway, list):
            highway = highway[0]

        # 2. 規則 A：如果是窄巷，成本變 3 倍 (讓駕駛傾向走大路)
        if highway in narrow_types:
            cost *= 70

        # 3. 規則 B：如果是單行道 (oneway)
        # 雖然 OSM 導航本來就不會逆向，但通常單行道較窄，我們加重 1.5 倍避開
        if data.get('oneway', False):
            cost *= 50

        # 4. 規則 C：如果是死巷，成本變 10 倍 (極度避開)
        if u in dead_end_nodes or v in dead_end_nodes:
            cost *= 100

        # 將最終計算的避險權重存入 dynamic_cost
        data['dynamic_cost'] = cost

    return G

with st.spinner("🌍 正在載入並計算避險路網權重..."):
    G_base = load_base_graph()


def get_precise_location(address, api_key):
    """使用 Google Geocoding API 將完整地址轉換為精確經緯度"""
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={api_key}&language=zh-TW"
    response = requests.get(url).json()

    if response['status'] == 'OK':
        lat = response['results'][0]['geometry']['location']['lat']
        lon = response['results'][0]['geometry']['location']['lng']
        return lat, lon
    else:
        raise ValueError(f"Google 找不到這個地址，請確認門牌是否正確：{address}")

# 3. 側邊欄介面
st.sidebar.header("🕹️ 導航控制")
start_loc = st.sidebar.text_input("📍 起點", value="臺南市中西區樹林街二段33號")
end_loc = st.sidebar.text_input("🏁 終點", value="臺南市中西區神農街135號") 
activate_bus = st.sidebar.checkbox("🚌 啟用公車動態避險", value=True)

# 4. 執行按鈕
if st.sidebar.button("開始導航 🚀", type="primary", use_container_width=True):
    with st.spinner("正在計算路徑..."):
        try:
            G_run = G_base.copy()

            # 從 .env 讀到的 ID 和 Secret
            if activate_bus:
                G_run = apply_bus_risk(G_run, TDX_CLIENT_ID, TDX_CLIENT_SECRET)

            # 網頁輸入完整地址！
            start_lat, start_lon = get_precise_location(start_loc, GOOGLE_API_KEY)
            end_lat, end_lon = get_precise_location(end_loc, GOOGLE_API_KEY)

            # 尋找最近節點
            orig = ox.distance.nearest_nodes(G_run, X=start_lon, Y=start_lat)
            dest = ox.distance.nearest_nodes(G_run, X=end_lon, Y=end_lat)

            truck_start_lat = G_run.nodes[orig]['y']
            truck_start_lon = G_run.nodes[orig]['x']
            truck_end_lat = G_run.nodes[dest]['y']
            truck_end_lon = G_run.nodes[dest]['x']

            # 計算路徑
            route = nx.shortest_path(G_run, orig, dest, weight='dynamic_cost')

            # 5. 畫地圖
            m = folium.Map(
                    location=[start_lat, start_lon], 
                    zoom_start=16, 
                    tiles='http://mt0.google.com/vt/lyrs=m&hl=zh-TW&x={x}&y={y}&z={z}',
                    attr='Google Maps'
                )

            route_coords = [[G_run.nodes[n]['y'], G_run.nodes[n]['x']] for n in route]

            full_route_coords = [[start_lat, start_lon]] + route_coords + [[end_lat, end_lon]]
            folium.PolyLine(route_coords, color="#00E676", weight=6, opacity=0.8).add_to(m)

            # 標示【客戶實際地址】
            folium.Marker(
                [end_lat, end_lon], 
                popup=f"📦 送貨目的地: {end_loc}", 
                icon=folium.Icon(color='blue', icon='home', prefix='fa')
            ).add_to(m)

            # 標示【貨車停靠點】(演算法算出來的最近大馬路)
            folium.Marker(
                [truck_end_lat, truck_end_lon], 
                popup="🚚 貨車最佳停靠/卸貨點", 
                icon=folium.Icon(color='red', icon='truck', prefix='fa')
            ).add_to(m)

            # 用一條淺灰色細線連接停車點與客戶家，代表「手推車步行距離」
            folium.PolyLine(
                [[truck_end_lat, truck_end_lon], [end_lat, end_lon]], 
                color="gray", weight=2, dash_array='5, 5', tooltip="司機推車步行路線"
            ).add_to(m)

            # 起點的貨車位置
            folium.Marker(
                [truck_start_lat, truck_start_lon], 
                popup=f"出發點 (近 {start_loc})", 
                icon=folium.Icon(color='green', icon='truck', prefix='fa')
            ).add_to(m)

            all_coords = route_coords + [[end_lat, end_lon]]
            m.fit_bounds(route_coords)

            import streamlit.components.v1 as components
            map_html = m._repr_html_()

            # 直接用 Streamlit 的 HTML 元件插入地圖
            components.html(map_html, height=600)

        except Exception as e:
            # 這裡會幫你印出具體的錯誤原因
            st.error(f"錯誤：{e}")
