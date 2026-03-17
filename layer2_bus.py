import requests
import pandas as pd

def get_bus_data_v3(route_name, client_id, client_secret):
    # 1. 取得 Token (保持你原本的 auth 邏輯)
    token = get_tdx_token(client_id, client_secret)
    if not token:
        return pd.DataFrame()

    # 2. 設定 v3 URL
    # 注意：{route_name} 直接帶入路線名稱，如 "2" 或 "6"
    url = f"https://tdx.transportdata.tw/api/basic/v3/Bus/RealTimeByFrequency/City/Tainan/{route_name}"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        res_data = response.json()

        # v3 的結構：主要資料在 'Buses' 陣列中
        buses = res_data.get('Buses', [])

        extracted_data = []
        for bus in buses:
            pos = bus.get('BusPosition', {})
            extracted_data.append({
                'PlateNumb': bus.get('PlateNumb'),
                'RouteName': bus.get('RouteName', {}).get('Zh_tw'),
                'Latitude': pos.get('PositionLat'),
                'Longitude': pos.get('PositionLon'),
                'BusStatus': bus.get('BusStatus'),
                'GPSTime': bus.get('GPSTime')
            })

        return pd.DataFrame(extracted_data)
    else:
        print(f"Error {response.status_code}: {response.text}")
        return pd.DataFrame()

# 使用範例
# df_bus = get_bus_data_v3("6", YOUR_ID, YOUR_SECRET)
# print(df_bus.head())
