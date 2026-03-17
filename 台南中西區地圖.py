import geopandas as gpd
import osmnx as ox
import folium
import math

# ===== API Key =====
GOOGLE_API_KEY = "AIzaSyDDn9Sq5cTUP_5mP5Ih2Zjbb2f6wp-kzbU"

# 讀取中西區 
shp_path = "/Users/bosichen/統一/村(里)界(TWD97經緯度)1150224/VILLAGE_NLSC_1150306.shp"
gdf = gpd.read_file(shp_path)
zhongxi = gdf[(gdf["COUNTYNAME"] == "臺南市") & (gdf["TOWNNAME"] == "中西區")]
boundary = zhongxi.union_all()

# 抓所有道路
print("正在抓取道路資料...")
G_all = ox.graph_from_polygon(boundary, network_type='all')
edges_all = ox.graph_to_gdfs(G_all, nodes=False)
print(f"共抓到 {len(edges_all)} 條道路")

# 抓可行駛道路判斷死巷（保留但不顯示）
print("正在判斷死巷...")
G_drive = ox.graph_from_polygon(boundary, network_type='drive')
dead_end_nodes = set([node for node, degree in G_drive.degree() if degree == 1])
print(f"找到 {len(dead_end_nodes)} 個死巷節點")

nodes_all, edges_all_reset = ox.graph_to_gdfs(G_all)
edges_all_reset = edges_all_reset.reset_index()

# 判斷單行道（只抓小路）
local_road_types = ['residential', 'service', 'living_street']
def is_oneway(row):
    highway = row.get('highway', '')
    if isinstance(highway, list):
        highway = highway[0]
    if highway not in local_road_types:
        return False
    return str(row.get('oneway', 'False')).lower() in ['yes', 'true', '1']

# 判斷嚴重堵塞（結合車道數和道路類型）
narrow_types = ['service', 'living_street', 'alley']
def is_narrow(row):
    lanes = row.get('lanes', None)
    if lanes is not None:
        try:
            if isinstance(lanes, list):
                lanes = lanes[0]
            lanes = int(str(lanes).strip())
            return lanes == 1
        except:
            pass
    highway = row.get('highway', '')
    if isinstance(highway, list):
        highway = highway[0]
    return highway in narrow_types

# 分類：單行道 > 嚴重堵塞 > 一般
def classify(row):
    if is_oneway(row):
        return 'oneway'
    elif is_narrow(row):
        return 'narrow'
    else:
        return 'normal'

print("正在分類道路...")
edges_all_reset['category'] = edges_all_reset.apply(classify, axis=1)
print(edges_all_reset['category'].value_counts())

# 顏色與標籤
color_map = {
    'oneway': '#F8981D',
    'narrow': '#5BBDC8',
    'normal': '#AAAAAA',
}
label_map = {
    'oneway': '單行道',
    'narrow': '嚴重堵塞',
    'normal': '一般道路',
}
weight_map = {
    'oneway': 3,
    'narrow': 2,
    'normal': 1.5,
}

# 建立 folium 地圖
center = [zhongxi.to_crs(epsg=4326).geometry.centroid.y.mean(),
          zhongxi.to_crs(epsg=4326).geometry.centroid.x.mean()]
m = folium.Map(location=center, zoom_start=15, tiles='CartoDB positron')

# 畫村里界
folium.GeoJson(
    zhongxi.__geo_interface__,
    style_function=lambda x: {
        'fillColor': 'transparent',
        'color': 'black',
        'weight': 2.5,
        'fillOpacity': 0,
    },
    tooltip=folium.GeoJsonTooltip(fields=['VILLNAME'], aliases=['村里：'])
).add_to(m)

# 畫道路
print("正在畫道路...")
for category in ['normal', 'narrow', 'oneway']:
    subset = edges_all_reset[edges_all_reset['category'] == category]
    if len(subset) == 0:
        continue
    print(f"畫 {label_map[category]}：{len(subset)} 條")

    for _, row in subset.iterrows():
        highway = row.get('highway', '未知')
        if isinstance(highway, list):
            highway = highway[0]
        name = row.get('name', '無名稱')
        if isinstance(name, list):
            name = name[0]

        try:
            coords = [(lat, lng) for lng, lat in row.geometry.coords]
        except:
            continue

        mid = len(coords) // 2
        lat, lng = coords[mid]

        if len(coords) >= 2:
            lat1, lng1 = coords[mid-1]
            lat2, lng2 = coords[mid]
            heading = math.degrees(math.atan2(lng2-lng1, lat2-lat1)) % 360
        else:
            heading = 0

        gsv_img_url = f"https://maps.googleapis.com/maps/api/streetview?size=400x250&location={lat},{lng}&heading={heading}&fov=90&pitch=0&key={GOOGLE_API_KEY}"
        gsv_link_url = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lng}&heading={heading}"

        popup_html = f"""
        <div style="font-family:Arial; font-size:13px; min-width:220px;">
            <b>{label_map[category]}</b><br>
            道路類型：{highway}<br>
            道路名稱：{name}<br><br>
            <img src="{gsv_img_url}" width="220px" style="border-radius:6px;"><br><br>
            <a href="{gsv_link_url}" target="_blank"
               style="background:#4285F4; color:white; padding:5px 10px;
                      border-radius:4px; text-decoration:none;">
               📍 開啟 Google Street View
            </a>
        </div>
        """

        folium.PolyLine(
            locations=coords,
            color=color_map[category],
            weight=weight_map[category],
            opacity=0.9,
            tooltip=f"{label_map[category]} | {highway} | {name}",
            popup=folium.Popup(popup_html, max_width=300)
        ).add_to(m)

        folium.PolyLine(
            locations=coords,
            color='black',
            weight=15,
            opacity=0,
            popup=folium.Popup(popup_html, max_width=300)
        ).add_to(m)

# 圖例
legend_html = """
<div style="position: fixed; bottom: 40px; right: 40px; z-index: 1000;
     background-color: white; padding: 15px; border-radius: 8px;
     box-shadow: 2px 2px 6px rgba(0,0,0,0.3); font-family: Arial;">
  <b style="font-size:14px;">台南市中西區配送困難路段</b><br><br>
  <span style="background:#F8981D; padding:3px 14px; margin-right:8px; border-radius:3px;"></span> 單行道<br><br>
  <span style="background:#5BBDC8; padding:3px 14px; margin-right:8px; border-radius:3px;"></span> 嚴重堵塞<br><br>
  <span style="background:#AAAAAA; padding:3px 14px; margin-right:8px; border-radius:3px;"></span> 一般道路<br>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

# 儲存
output_path = "/Users/bosichen/統一/zhongxi_interactive_map.html"
m.save(output_path)
print(f"完成！用 Chrome 開啟 {output_path}")