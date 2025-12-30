import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

def plot_pressure_history(lat, lon, target_datetime_str):
    # 1. 日時の処理 (前後24時間を取得対象にする)
    target_dt = datetime.strptime(target_datetime_str, '%Y-%m-%d %H:%M')
    start_date = (target_dt - timedelta(days=1)).strftime('%Y-%m-%d')
    end_date = (target_dt + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # 2. Open-Meteo API (アーカイブ/予報) からデータを取得
    # ※過去データと予報データの両方をカバーするため、ここではforecastエンドポイントを使用
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "surface_pressure",
        "start_date": start_date,
        "end_date": end_date,
        "timezone": "Asia/Tokyo"
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    # 3. データ整理
    df = pd.DataFrame({
        "time": pd.to_datetime(data["hourly"]["time"]),
        "pressure": data["hourly"]["surface_pressure"]
    })
    
    # 4. 可視化
    plt.figure(figsize=(10, 5))
    plt.plot(df['time'], df['pressure'], marker='o', markersize=4, label='Pressure (hPa)')
    
    # 指定した「頭痛発生日時」に垂直線を引く
    plt.axvline(x=target_dt, color='red', linestyle='--', label='Headache Event')
    
    plt.title(f"Pressure Trend around {target_datetime_str}")
    plt.xlabel("Time")
    plt.ylabel("hPa")
    plt.grid(True)
    plt.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # グラフを表示（保存）
    plt.savefig("pressure_plot.png")
    print("グラフを 'pressure_plot.png' として保存しました。")

# 実行例（東京：35.68, 139.69 / 2025年12月26日 10:00の前後）
plot_pressure_history(35.6895, 139.6917, "2025-12-26 10:00")