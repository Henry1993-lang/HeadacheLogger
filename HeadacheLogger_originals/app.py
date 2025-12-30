import streamlit as st
import json
import os
import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
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

# --- Helper Functions ---

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
            try:
                current_config = json.load(f)
            except json.JSONDecodeError:
                current_config = {}
    
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

def save_config(config):
    """Save configuration to config.json."""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

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

def delete_logs(indices_to_delete):
    """Delete logs at specific indices."""
    if not os.path.exists(LOG_FILE):
        return
    
    df = pd.read_csv(LOG_FILE)
    df = df.drop(indices_to_delete)
    df.to_csv(LOG_FILE, index=False, encoding='utf-8')
    st.cache_data.clear() # Clear cache to reflect changes if necessary

def load_history_data():
    """Load history from CSV for dashboard."""
    if not os.path.exists(LOG_FILE):
        return pd.DataFrame()
    df = pd.read_csv(LOG_FILE)
    if 'datetime' in df.columns:
        df['datetime'] = pd.to_datetime(df['datetime'])
    return df

def render_dashboard(df_history):
    """
    分析ダッシュボードを描画する関数
    :param df_history: 履歴DataFrame
    """
    if df_history.empty:
        st.info("分析用のデータがまだありません。記録を追加してください。")
        return

    # 1. KPI カード
    st.markdown("### 📈 サマリー")
    kpi1, kpi2, kpi3 = st.columns(3)
    
    total_logs = len(df_history)
    avg_pain = df_history['pain_level'].mean()
    # 最大気圧低下: pressure_delta_3h の最小値
    max_drop = df_history['pressure_delta_3h'].min()
    
    kpi1.metric("総記録数", f"{total_logs} 件")
    kpi2.metric("平均痛みレベル", f"{avg_pain:.1f}")
    kpi3.metric("最大気圧低下 (3h)", f"{max_drop} hPa")
    
    st.divider()

    # 2. 散布図: 気圧低下 vs 痛み
    st.markdown("### 💥 気圧低下と痛みの関係")
    
    # データを準備
    fig_scatter = px.scatter(
        df_history,
        x="pressure_delta_3h",
        y="pain_level",
        color="pressure_trend",
        labels={
            "pressure_delta_3h": "3時間気圧変化 (hPa)",
            "pain_level": "痛みレベル (0-10)",
            "pressure_trend": "気圧傾向"
        },
        title="気圧変化量 vs 痛みレベル",
        hover_data=["datetime", "memo", "location_name"],
        height=400
    )
    
    # 警戒ライン (-1.0 hPa)
    fig_scatter.add_vline(
        x=-1.0, 
        line_dash="dash", 
        line_color="red", 
        annotation_text="警戒ライン (-1.0 hPa)",
        annotation_position="top left"
    )
    
    st.plotly_chart(fig_scatter, use_container_width=True)
    
    st.divider()

    # 3. ヒートマップ: 曜日 vs 時間帯
    st.markdown("### 📅 発生パターン (曜日×時間)")
    
    # データ加工
    df_heat = df_history.copy()
    df_heat['Weekday'] = df_heat['datetime'].dt.day_name()
    df_heat['Hour'] = df_heat['datetime'].dt.hour
    
    # 曜日の順序定義
    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    # ヒートマップ描画 (Z軸: 平均痛みレベル)
    fig_heat = px.density_heatmap(
        df_heat,
        x="Weekday",
        y="Hour",
        z="pain_level",
        histfunc="avg", # 平均値を計算
        category_orders={"Weekday": days_order},
        range_y=[0, 23],
        nbinsy=24,
        labels={
            "Weekday": "曜日",
            "Hour": "時間帯 (時)",
            "pain_level": "平均痛みレベル"
        },
        title="曜日・時間帯別の平均痛みレベル",
        color_continuous_scale="Reds",
        height=400
    )
    
    st.plotly_chart(fig_heat, use_container_width=True)

# --- Main Application ---

def main():
    st.title("🌡️ Headache Pressure Logger")
    st.markdown("気圧変化と頭痛の相関を記録・分析するためのツール")

    config = load_config()

    # --- Sidebar: Settings ---
    with st.sidebar:
        # Settings Expander
        with st.expander("⚙️ 設定 (場所・要因)"):
            st.subheader("📍 場所管理")
            
            # Add New Location
            with st.form("add_location_form"):
                new_loc_name = st.text_input("名前 (例: 職場)")
                new_loc_lat = st.number_input("緯度", value=35.6895, format="%.4f")
                new_loc_lon = st.number_input("経度", value=139.6917, format="%.4f")
                submitted = st.form_submit_button("場所を追加")
                
                if submitted:
                    if new_loc_name:
                        new_loc = {"name": new_loc_name, "lat": new_loc_lat, "lon": new_loc_lon}
                        config["locations"].append(new_loc)
                        save_config(config)
                        st.success(f"'{new_loc_name}' を追加しました！")
                        st.rerun()
                    else:
                        st.error("名前を入力してください。")

            # Remove Location
            loc_names_to_remove = [loc["name"] for loc in config["locations"]]
            loc_to_remove = st.selectbox("削除する場所", ["(選択してください)"] + loc_names_to_remove)
            if loc_to_remove != "(選択してください)":
                if st.button("場所を削除"):
                    config["locations"] = [loc for loc in config["locations"] if loc["name"] != loc_to_remove]
                    # Adjust default index if needed
                    if config["default_location_index"] >= len(config["locations"]):
                        config["default_location_index"] = 0
                    save_config(config)
                    st.success(f"'{loc_to_remove}' を削除しました。")
                    st.rerun()

            st.divider()
            st.subheader("🏷️ 要因タグ管理")
            
            # Manage Factors
            current_factors = config.get("factor_options", [])
            factors_text = st.text_area("要因リスト (カンマ区切りで編集)", ", ".join(current_factors))
            
            if st.button("要因リストを更新"):
                new_factors = [f.strip() for f in factors_text.split(',') if f.strip()]
                config["factor_options"] = new_factors
                save_config(config)
                st.success("要因リストを更新しました！")
                st.rerun()
        
    # --- Tabs ---
    tab_record, tab_analytics = st.tabs(["📝 記録入力", "📊 分析ダッシュボード"])

    # --- Tab 1: Record ---
    with tab_record:
        col_input, col_viz = st.columns([1, 2])
        
        with col_input:
            st.subheader("新規記録")
            
            input_date = st.date_input("日付", datetime.now())
            input_time = st.time_input("時間", datetime.now().time())
            target_dt = datetime.combine(input_date, input_time)

            pain_level = st.slider("痛みのレベル (0-10)", 0, 10, 5)

            location_names = [loc["name"] for loc in config["locations"]]
            default_idx = config.get("default_location_index", 0)
            if default_idx >= len(location_names):
                default_idx = 0
            
            selected_loc_name = st.selectbox("場所", location_names, index=default_idx)
            selected_location = next((loc for loc in config["locations"] if loc["name"] == selected_loc_name), config["locations"][0])

            factor_options = config.get("factor_options", [])
            selected_factors = st.multiselect("要因", factor_options)

            memo = st.text_area("メモ", height=80)

            fetch_btn = st.button("気圧データを取得 & 分析", type="primary")

        # Session State for Analysis
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
                    st.session_state['analyzed_data'] = {
                        'df': df,
                        'features': features
                    }
                    st.session_state['target_dt'] = target_dt
                    st.session_state['selected_location'] = selected_location
                else:
                    st.error("特徴量の計算に失敗しました。")

        # Visualization
        with col_viz:
            if st.session_state['analyzed_data']:
                data = st.session_state['analyzed_data']
                df = data['df']
                features = data['features']
                
                display_dt = st.session_state.get('target_dt', target_dt)
                display_loc = st.session_state.get('selected_location', selected_location)

                # Metrics
                st.subheader("📊 分析結果")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("現在気圧", f"{features['pressure_current']} hPa", f"{features['pressure_trend']}")
                m2.metric("3h変化", f"{features['pressure_delta_3h']} hPa", delta_color="inverse")
                m3.metric("12h変化", f"{features['pressure_delta_12h']} hPa", delta_color="inverse")
                m4.metric("12h最低", f"{features['pressure_min_12h']} hPa")

                # Chart
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df.index, 
                    y=df['pressure'],
                    mode='lines+markers',
                    name='気圧 (hPa)',
                    line=dict(color='royalblue', width=2)
                ))
                fig.add_vline(x=display_dt, line_width=2, line_dash="dash", line_color="red")
                fig.add_annotation(x=display_dt, y=1.02, yref="paper", text="Event", showarrow=False, font=dict(color="red"))
                fig.update_layout(
                    title=f"{display_loc['name']} の気圧推移",
                    xaxis_title="日時",
                    yaxis_title="気圧 (hPa)",
                    height=400,
                    margin=dict(l=20, r=20, t=40, b=20)
                )
                st.plotly_chart(fig, use_container_width=True)

                # Save Button
                st.divider()
                if st.button("ログに保存する"):
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
                    save_log(log_data)
                    st.success(f"記録を保存しました！ ({display_dt.strftime('%Y-%m-%d %H:%M')})")
                    st.balloons()
                    # Optional: Clear state or rerun
                    # st.session_state['analyzed_data'] = None
                    # st.rerun()

        # History List
        st.divider()
        st.subheader("📜 履歴管理")
        if os.path.exists(LOG_FILE):
            history_df = pd.read_csv(LOG_FILE)
            history_df['Delete'] = False
            
            # Reorder
            cols = ['Delete'] + [c for c in history_df.columns if c != 'Delete']
            history_df = history_df[cols]

            edited_df = st.data_editor(
                history_df.sort_values(by="datetime", ascending=False),
                num_rows="fixed",
                hide_index=True,
                column_config={
                    "Delete": st.column_config.CheckboxColumn("削除", width="small")
                }
            )

            if st.button("チェックしたログを削除"):
                to_delete = edited_df[edited_df['Delete']]
                if not to_delete.empty:
                    indices_to_drop = to_delete.index.tolist()
                    delete_logs(indices_to_drop)
                    st.success(f"{len(indices_to_drop)} 件のログを削除しました。")
                    st.rerun()
        else:
            st.info("まだログはありません。")

    # --- Tab 2: Analytics ---
    with tab_analytics:
        st.header("📊 統計ダッシュボード")
        df_history = load_history_data()
        render_dashboard(df_history)

if __name__ == "__main__":
    main()
