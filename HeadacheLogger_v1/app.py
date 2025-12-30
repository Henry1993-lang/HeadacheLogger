import streamlit as st
import json
import os
import requests
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, time

# --- Constants ---
CONFIG_FILE = 'config.json'
LOG_FILE = 'headache_log.csv'
API_URL = "https://api.open-meteo.com/v1/forecast"
TIMEZONE = "Asia/Tokyo"

# --- Page Configuration ---
st.set_page_config(
    page_title="Headache Pressure Logger",
    page_icon="🌡️",
    layout="wide"
)

# --- Helper Functions (Inherited & Adapted from hbl_logger.py) ---

def load_config():
    """Load configuration from config.json. Creates default if not exists."""
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
    
    # Merge defaults
    for key, value in default_config.items():
        if key not in current_config:
            current_config[key] = value
        elif key == "factor_options" and not current_config[key]:
            current_config[key] = value

    if not os.path.exists(CONFIG_FILE) or current_config != default_config:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_config, f, ensure_ascii=False, indent=2)
    
    return current_config

@st.cache_data(ttl=3600) # Cache for 1 hour to avoid excessive API calls
def get_pressure_data(lat, lon, target_dt):
    """Fetch pressure data from Open-Meteo API."""
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
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"天気データの取得中にエラーが発生しました: {e}")
        return None

    if "hourly" not in data or not data["hourly"]["time"] or not data["hourly"]["surface_pressure"]:
        st.error("天気データが取得できませんでした。")
        return None
    
    df = pd.DataFrame({
        "time": pd.to_datetime(data["hourly"]["time"]),
        "pressure": data["hourly"]["surface_pressure"]
    })
    df.set_index("time", inplace=True)
    return df

def calculate_pressure_features(df, target_dt):
    """Calculate pressure features from DataFrame."""
    target_dt_naive = target_dt.replace(tzinfo=None) 

    if df.empty:
        return None
    
    # Find closest time index
    actual_target_time = min(df.index, key=lambda x: abs(x - target_dt_naive))
    
    pressure_current = df.loc[actual_target_time, 'pressure']
    
    def get_pressure_at_offset(offset_hours):
        offset_time = actual_target_time - timedelta(hours=offset_hours)
        if offset_time in df.index:
            return df.loc[offset_time, 'pressure']
        if df.index.min() <= offset_time <= df.index.max():
            closest_offset_time_in_df = min(df.index, key=lambda x: abs(x - offset_time))
            return df.loc[closest_offset_time_in_df, 'pressure']
        return pressure_current

    pressure_1h_ago = get_pressure_at_offset(1)
    pressure_3h_ago = get_pressure_at_offset(3)
    pressure_12h_ago = get_pressure_at_offset(12)
    pressure_24h_ago = get_pressure_at_offset(24)

    pressure_delta_1h = pressure_current - pressure_1h_ago
    pressure_delta_3h = pressure_current - pressure_3h_ago
    pressure_delta_12h = pressure_current - pressure_12h_ago
    pressure_delta_24h = pressure_current - pressure_24h_ago
    
    past_12h_df = df.loc[actual_target_time - timedelta(hours=12) : actual_target_time]
    pressure_min_12h = past_12h_df['pressure'].min() if not past_12h_df.empty else pressure_current
    
    trend = "不明"
    if pressure_delta_3h < -1.0:
        trend = "急降下"
    elif pressure_delta_3h < -0.3:
        trend = "下降中"
    elif pressure_delta_3h > 1.0:
        trend = "急上昇"
    elif pressure_delta_3h > 0.3:
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

def save_log(data):
    """Append log data to CSV."""
    file_exists = os.path.isfile(LOG_FILE)
    df_new = pd.DataFrame([data])
    
    # Define columns to ensure order
    columns = [
        "datetime", "lat", "lon", "location_name", "pain_level", "factors", "memo",
        "pressure_current", "pressure_delta_1h", "pressure_delta_3h",
        "pressure_delta_12h", "pressure_delta_24h", "pressure_min_12h", "pressure_trend"
    ]
    
    # Ensure all columns exist
    for col in columns:
        if col not in df_new.columns:
            df_new[col] = None

    if not file_exists:
        df_new[columns].to_csv(LOG_FILE, index=False, encoding='utf-8')
    else:
        df_new[columns].to_csv(LOG_FILE, mode='a', header=False, index=False, encoding='utf-8')

# --- Main Application ---

def main():
    st.title("🌡️ Headache Pressure Logger")
    st.markdown("気圧変化と頭痛の相関を記録・分析するためのツール")

    config = load_config()

    # --- Sidebar: User Inputs ---
    with st.sidebar:
        st.header("📝 記録入力")
        
        # DateTime Input
        col1, col2 = st.columns(2)
        with col1:
            input_date = st.date_input("日付", datetime.now())
        with col2:
            input_time = st.time_input("時間", datetime.now().time())
        
        target_dt = datetime.combine(input_date, input_time)

        # Pain Level
        pain_level = st.slider("痛みのレベル (0-10)", 0, 10, 5)

        # Location
        location_names = [loc["name"] for loc in config["locations"]]
        default_idx = config.get("default_location_index", 0)
        selected_loc_name = st.selectbox("場所", location_names, index=default_idx)
        selected_location = next((loc for loc in config["locations"] if loc["name"] == selected_loc_name), config["locations"][0])

        # Factors
        factor_options = config.get("factor_options", [])
        selected_factors = st.multiselect("要因", factor_options)

        # Memo
        memo = st.text_area("メモ", height=80)

        fetch_btn = st.button("気圧データを取得 & 分析", type="primary")

    # --- Main Area ---
    
    # Initialize session state for data persistence
    if 'analyzed_data' not in st.session_state:
        st.session_state['analyzed_data'] = None
    if 'target_dt' not in st.session_state:
        st.session_state['target_dt'] = None
    if 'selected_location' not in st.session_state:
        st.session_state['selected_location'] = None

    if fetch_btn:
        with st.spinner('気圧データを取得中...'):
            df = get_pressure_data(selected_location['lat'], selected_location['lon'], target_dt)
            
        if df is not None:
            features = calculate_pressure_features(df, target_dt)
            
            if features:
                # Store results in session state
                st.session_state['analyzed_data'] = {
                    'df': df,
                    'features': features
                }
                # Store context
                st.session_state['target_dt'] = target_dt
                st.session_state['selected_location'] = selected_location
            else:
                st.error("特徴量の計算に失敗しました。")

    # Check if we have analyzed data to display
    if st.session_state['analyzed_data']:
        data = st.session_state['analyzed_data']
        df = data['df']
        features = data['features']
        
        # Use stored context or fall back to current widgets (though stored is safer for consistency)
        display_dt = st.session_state.get('target_dt', target_dt)
        display_loc = st.session_state.get('selected_location', selected_location)

        # --- Metrics Display ---
        st.subheader("📊 気圧分析結果")
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("現在気圧", f"{features['pressure_current']} hPa", f"{features['pressure_trend']}")
        m2.metric("3時間変化", f"{features['pressure_delta_3h']} hPa", delta_color="inverse")
        m3.metric("12時間変化", f"{features['pressure_delta_12h']} hPa", delta_color="inverse")
        m4.metric("12時間最低", f"{features['pressure_min_12h']} hPa")

        # --- Plotly Chart ---
        st.subheader("📈 気圧推移 (前後24時間)")
        
        fig = go.Figure()
        
        # Pressure Line
        fig.add_trace(go.Scatter(
            x=df.index, 
            y=df['pressure'],
            mode='lines+markers',
            name='気圧 (hPa)',
            line=dict(color='royalblue', width=2)
        ))

        # Highlight Target Window (+/- 6h)
        start_window = display_dt - timedelta(hours=6)
        end_window = display_dt + timedelta(hours=6)
        
        # Vertical Line at Event
        fig.add_vline(x=display_dt, line_width=2, line_dash="dash", line_color="red", annotation_text="Event")

        # Layout
        fig.update_layout(
            title=f"{display_loc['name']} の気圧推移",
            xaxis_title="日時",
            yaxis_title="気圧 (hPa)",
            hovermode="x unified",
            height=500
        )
        
        st.plotly_chart(fig, use_container_width=True)

        # --- Save Section ---
        st.divider()
        st.info("内容を確認して、問題なければ保存してください。")
        
        # Prepare data for saving
        # Note: We use current widget values for pain/factors/memo as user might edit them after fetch
        log_data = {
            "datetime": display_dt.strftime('%Y-%m-%d %H:%M'),
            "lat": display_loc['lat'],
            "lon": display_loc['lon'],
            "location_name": display_loc['name'],
            "pain_level": pain_level,
            "factors": '|'.join(selected_factors),
            "memo": memo,
            **features
        }
        
        if st.button("ログに保存する"):
            save_log(log_data)
            st.success(f"記録を保存しました！ ({display_dt.strftime('%Y-%m-%d %H:%M')})")
            st.balloons()
            # Optional: Clear state to reset view
            # st.session_state['analyzed_data'] = None
            # st.rerun()

    # --- History (Optional: Show recent logs) ---
    st.divider()
    with st.expander("📂 過去のログを確認する"):
        if os.path.exists(LOG_FILE):
            history_df = pd.read_csv(LOG_FILE)
            st.dataframe(history_df.sort_values(by="datetime", ascending=False))
        else:
            st.write("まだログはありません。")

if __name__ == "__main__":
    main()
