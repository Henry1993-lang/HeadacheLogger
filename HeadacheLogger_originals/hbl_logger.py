import json
import os
import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import re # For parsing factors

# --- Constants ---
CONFIG_FILE = 'config.json'
LOG_FILE = 'headache_log.csv'
PLOTS_DIR = 'plots'
API_URL = "https://api.open-meteo.com/v1/forecast"
TIMEZONE = "Asia/Tokyo"

# --- Config Management ---
def load_config():
    # Define default config structure
    default_config = {
        "locations": [
            {"name": "自宅 (東京)", "lat": 35.6895, "lon": 139.6917}
        ],
        "default_location_index": 0,
        "factor_options": [
            "寝不足", "ストレス", "アルコール", "PC作業過多", "女性ホルモン", "気候変動", "その他"
        ]
    }

    current_config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            current_config = json.load(f)
    
    # Merge default_config with current_config to add missing keys (like factor_options)
    # This ensures backward compatibility if config.json already exists but lacks new keys
    for key, value in default_config.items():
        if key not in current_config:
            current_config[key] = value
        # Special handling for factor_options if it's empty or different from default
        elif key == "factor_options" and not current_config[key]:
            current_config[key] = value

    if not os.path.exists(CONFIG_FILE) or current_config != default_config:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_config, f, ensure_ascii=False, indent=2)
        if not os.path.exists(CONFIG_FILE): # First time creation
            print(f"'{CONFIG_FILE}' を作成し、デフォルト設定を書き込みました。必要に応じて編集してください。")
        else: # Updated existing config
            print(f"'{CONFIG_FILE}' を更新しました。新しい設定オプションが追加されている可能性があります。")
    
    return current_config

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def add_new_location_to_config(config, name, lat, lon):
    config["locations"].append({"name": name, "lat": lat, "lon": lon})
    save_config(config)
    print(f"場所 '{name}' を設定に追加しました。")

# --- User Input Functions ---
def get_user_datetime():
    while True:
        dt_str = input(f"頭痛が発生した日時を入力してください (例: {datetime.now().strftime('%Y-%m-%d %H:%M')}) [Enterで現在時刻]: ").strip()
        if not dt_str:
            return datetime.now()
        try:
            return datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
        except ValueError:
            print("無効な日時フォーマットです。'YYYY-MM-DD HH:MM' の形式で入力してください。")

def get_pain_level():
    while True:
        level_str = input("痛みのレベルを0-10で入力してください (0:なし, 10:最悪) [5]: ").strip()
        if not level_str:
            return 5
        try:
            level = int(level_str)
            if 0 <= level <= 10:
                return level
            else:
                print("0から10の範囲で入力してください。")
        except ValueError:
            print("無効な入力です。数値を入力してください。")

def get_location_choice(config):
    locations = config["locations"]
    default_idx = config["default_location_index"]
    
    print("\n場所を選択してください:")
    for i, loc in enumerate(locations):
        default_tag = " *Default" if i == default_idx else ""
        print(f"{i}. {loc['name']}{default_tag}")
    print(f"{len(locations)}. その他 (緯度/経度を手動入力)")
    
    while True:
        choice_str = input(f"選択肢の番号を入力してください [{default_idx}]: ").strip()
        try:
            choice = int(choice_str) if choice_str else default_idx
            if 0 <= choice < len(locations):
                return locations[choice]
            elif choice == len(locations):
                name = input("新しい場所の名前を入力してください (例: 出張先): ").strip()
                while not name:
                    name = input("場所の名前は必須です: ").strip()
                while True:
                    try:
                        lat = float(input("緯度を入力してください (例: 35.6): "))
                        lon = float(input("経度を入力してください (例: 139.7): "))
                        break
                    except ValueError:
                        print("緯度と経度は数値で入力してください。")
                
                add_choice = input(f"この場所 '{name}' ({lat}, {lon}) を設定に保存しますか？ (y/N): ").lower()
                if add_choice == 'y':
                    add_new_location_to_config(config, name, lat, lon)
                return {"name": name, "lat": lat, "lon": lon}
            else:
                print("無効な選択です。")
        except ValueError:
            print("無効な入力です。数値を入力してください。")

def get_factor_choices(config):
    factor_options = config.get("factor_options", [])
    if not factor_options:
        print("設定ファイルに要因オプションがありません。デフォルトオプションが読み込まれます。")
        # Fallback to hardcoded defaults if config was completely malformed or missing key
        factor_options = [ "寝不足", "ストレス", "アルコール", "PC作業過多", "女性ホルモン", "気候変動", "その他" ]

    print("\n関連しそうな要因を選択してください (複数選択可、カンマ区切り):")
    for i, factor in enumerate(factor_options):
        print(f"{i+1}: {factor}")
    print("または空エンターでスキップ。")

    while True:
        selection_str = input("選択番号を入力 (例: 1,3) []: ").strip()
        if not selection_str:
            return []
        
        selected_factors = []
        try:
            choices = [int(s.strip()) for s in selection_str.split(',') if s.strip()]
            for choice in choices:
                if 1 <= choice <= len(factor_options):
                    selected_factors.append(factor_options[choice-1])
                else:
                    print(f"'{choice}' は無効な番号です。有効な番号を選択してください。")
                    selected_factors = [] # Clear invalid selection
                    break
            if selected_factors:
                return selected_factors
        except ValueError:
            print("無効な入力です。数字をカンマで区切って入力してください。")

def get_memo():
    return input("メモ (例: 薬を服用): ").strip()

# --- Weather Data & Feature Calculation ---
def get_pressure_data(lat, lon, target_dt):
    # Fetch 24 hours before to 24 hours after target_dt (total 48 hours for calculation)
    start_date = (target_dt - timedelta(hours=24)).strftime('%Y-%m-%d')
    end_date = (target_dt + timedelta(hours=24)).strftime('%Y-%m-%d')
    
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "surface_pressure",
        "start_date": start_date,
        "end_date": end_date,
        "timezone": TIMEZONE
    }
    
    try:
        response = requests.get(API_URL, params=params)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        data = response.json()
    except requests.exceptions.RequestException as e:
        print(f"天気データの取得中にエラーが発生しました: {e}")
        return None

    if "hourly" not in data or not data["hourly"]["time"] or not data["hourly"]["surface_pressure"]:
        print("天気データが取得できませんでした。")
        return None
    
    df = pd.DataFrame({
        "time": pd.to_datetime(data["hourly"]["time"]),
        "pressure": data["hourly"]["surface_pressure"]
    })
    df.set_index("time", inplace=True)
    
    return df

def calculate_pressure_features(df, target_dt):
    # Ensure target_dt is timezone-naive for direct comparison with DataFrame index
    target_dt_naive = target_dt.replace(tzinfo=None) 

    if df.empty:
        return None
    
    # Find the closest time entry to target_dt_naive
    # More robust way to find nearest index across different pandas versions
    actual_target_time = min(df.index, key=lambda x: abs(x - target_dt_naive))
    
    pressure_current = df.loc[actual_target_time, 'pressure']
    
    # Helper to get pressure at a specific offset, falling back to current if not found
    def get_pressure_at_offset(offset_hours):
        offset_time = actual_target_time - timedelta(hours=offset_hours)
        
        # If the exact offset time is in the index, return its pressure
        if offset_time in df.index:
            return df.loc[offset_time, 'pressure']
        
        # Otherwise, find the nearest available point within the dataframe's time range
        # Check if offset_time is within the dataframe's index range
        if df.index.min() <= offset_time <= df.index.max():
            # Find the closest time in the index to offset_time
            closest_offset_time_in_df = min(df.index, key=lambda x: abs(x - offset_time))
            return df.loc[closest_offset_time_in_df, 'pressure']
        
        # If offset_time is completely out of bounds, fall back to current pressure
        return pressure_current

    pressure_1h_ago = get_pressure_at_offset(1)
    pressure_3h_ago = get_pressure_at_offset(3)
    pressure_12h_ago = get_pressure_at_offset(12)
    pressure_24h_ago = get_pressure_at_offset(24)

    pressure_delta_1h = pressure_current - pressure_1h_ago
    pressure_delta_3h = pressure_current - pressure_3h_ago
    pressure_delta_12h = pressure_current - pressure_12h_ago
    pressure_delta_24h = pressure_current - pressure_24h_ago
    
    # Past 12 hours (including current hour) for min/max
    # Use .between to ensure proper range selection
    past_12h_df = df.loc[actual_target_time - timedelta(hours=12) : actual_target_time]
    pressure_min_12h = past_12h_df['pressure'].min() if not past_12h_df.empty else pressure_current
    
    # Trend (simple categorization)
    trend = "不明"
    if pressure_delta_3h < -1.0: # Significant drop over 3 hours
        trend = "急降下"
    elif pressure_delta_3h < -0.3: # Moderate drop
        trend = "下降中"
    elif pressure_delta_3h > 1.0: # Significant rise
        trend = "急上昇"
    elif pressure_delta_3h > 0.3: # Moderate rise
        trend = "上昇中"
    else:
        trend = "安定"

    return {
        "pressure_current": round(pressure_current, 2),
        "pressure_delta_1h": round(pressure_delta_1h, 2),
        "pressure_delta_3h": round(pressure_delta_3h, 2),
        "pressure_delta_12h": round(pressure_delta_12h, 2),
        "pressure_delta_24h": round(pressure_delta_24h, 2),
        "pressure_min_12h": round(pressure_min_12h, 2),
        "pressure_trend": trend
    }

# --- Logging ---
def log_to_csv(data):
    file_exists = os.path.isfile(LOG_FILE)
    df_new = pd.DataFrame([data])
    
    if not file_exists:
        # Define columns explicitly for the first write to ensure order
        columns = [
            "datetime", "lat", "lon", "location_name", "pain_level", "factors", "memo",
            "pressure_current", "pressure_delta_1h", "pressure_delta_3h",
            "pressure_delta_12h", "pressure_delta_24h", "pressure_min_12h", "pressure_trend"
        ]
        df_new[columns].to_csv(LOG_FILE, index=False, encoding='utf-8')
    else:
        df_new.to_csv(LOG_FILE, mode='a', header=False, index=False, encoding='utf-8')
    print(f"データを '{LOG_FILE}' に保存しました。")

# --- Plotting ---
def plot_pressure_history(df, target_dt, location_name, output_filename):
    os.makedirs(PLOTS_DIR, exist_ok=True)
    
    plt.figure(figsize=(12, 6))
    plt.plot(df.index, df['pressure'], marker='o', markersize=3, linestyle='-', label='Pressure (hPa)')
    
    # Highlight the target_dt +/- 6 hours range
    plot_start = target_dt - timedelta(hours=6)
    plot_end = target_dt + timedelta(hours=6)
    
    plt.axvspan(plot_start, plot_end, color='yellow', alpha=0.2, label='Target Window (+/-6h)')
    plt.axvline(x=target_dt, color='red', linestyle='--', label='Headache Event')
    
    plt.title(f"Pressure Trend for {location_name} around {target_dt.strftime('%Y-%m-%d %H:%M')}")
    plt.xlabel("Time")
    plt.ylabel("Pressure (hPa)")
    plt.grid(True)
    plt.legend()
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, output_filename))
    plt.close() # Close plot to free memory
    print(f"グラフを '{os.path.join(PLOTS_DIR, output_filename)}' として保存しました。")

# --- Main Logic ---
def main():
    config = load_config()

    print("\n=== 頭痛気圧ロガー ===")

    # 1. Get DateTime
    event_datetime = get_user_datetime()

    # 2. Get Pain Level
    pain_level = get_pain_level()

    # 3. Get Location
    selected_location = get_location_choice(config)

    # 4. Get Factors
    selected_factors = get_factor_choices(config)

    # 5. Get Memo
    memo = get_memo()

    # --- Fetch and Calculate Pressure Data ---
    print(f"\n場所: {selected_location['name']} ({selected_location['lat']},{selected_location['lon']})")
    print(f"日時: {event_datetime.strftime('%Y-%m-%d %H:%M')}")
    print("気圧データを取得中...")

    pressure_df = get_pressure_data(selected_location['lat'], selected_location['lon'], event_datetime)
    
    if pressure_df is None:
        print("気圧データの取得に失敗したため、記録を中断します。")
        return

    pressure_features = calculate_pressure_features(pressure_df, event_datetime)

    if pressure_features is None:
        print("気圧特徴量の計算に失敗したため、記録を中断します。")
        return

    print("\n--- 記録データ ---")
    print(f"日時: {event_datetime.strftime('%Y-%m-%d %H:%M')}")
    print(f"場所: {selected_location['name']}")
    print(f"痛みレベル: {pain_level}")
    print(f"要因: {', '.join(selected_factors) if selected_factors else 'なし'}")
    print(f"メモ: {memo if memo else 'なし'}")
    print(f"現在気圧: {pressure_features['pressure_current']} hPa")
    print(f"気圧変化 (過去1h): {pressure_features['pressure_delta_1h']} hPa")
    print(f"気圧変化 (過去3h): {pressure_features['pressure_delta_3h']} hPa")
    print(f"気圧変化 (過去12h): {pressure_features['pressure_delta_12h']} hPa")
    print(f"気圧変化 (過去24h): {pressure_features['pressure_delta_24h']} hPa")
    print(f"過去12h最低気圧: {pressure_features['pressure_min_12h']} hPa")
    print(f"気圧トレンド: {pressure_features['pressure_trend']}")

    # --- Prepare data for CSV ---
    log_data = {
        "datetime": event_datetime.strftime('%Y-%m-%d %H:%M'),
        "lat": selected_location['lat'],
        "lon": selected_location['lon'],
        "location_name": selected_location['name'],
        "pain_level": pain_level,
        "factors": '|'.join(selected_factors), # Use pipe for easy splitting later
        "memo": memo,
        **pressure_features # Unpack all calculated features
    }

    # --- Log to CSV ---
    log_to_csv(log_data)

    # --- Plotting ---
    plot_filename = f"{event_datetime.strftime('%Y%m%d_%H%M')}_{selected_location['name']}.png"
    plot_pressure_history(pressure_df, event_datetime, selected_location['name'], plot_filename)
    
    print("\n記録が完了しました。")

if __name__ == "__main__":
    main()