import streamlit as st
import json
import os
import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, time
from supabase import create_client, Client

# --- Constants ---
CONFIG_FILE = 'config.json'
API_URL = "https://api.open-meteo.com/v1/forecast"
TIMEZONE = "Asia/Tokyo"

# --- Page Configuration ---
st.set_page_config(
    page_title="Headache Pressure Logger v2.0",
    page_icon="🌡️",
    layout="wide"
)

# --- Supabase Initialization ---
@st.cache_resource
def init_supabase() -> Client:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Supabase configuration error: {e}")
        st.stop()

supabase = init_supabase()

# --- Helper Functions (Config) ---
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

# --- Helper Functions (Weather API) ---
@st.cache_data(ttl=3600)
def get_pressure_data(lat, lon, target_dt):
    """Fetch pressure data from Open-Meteo API."""
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
        st.error(f"Weather API Error: {e}")
        return None

    if "hourly" not in data or not data["hourly"]["time"]:
        st.error("No weather data available.")
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
    
    actual_target_time = min(df.index, key=lambda x: abs(x - target_dt_naive))
    pressure_current = df.loc[actual_target_time, 'pressure']
    
    def get_pressure_at_offset(offset_hours):
        offset_time = actual_target_time - timedelta(hours=offset_hours)
        if offset_time in df.index:
            return df.loc[offset_time, 'pressure']
        if df.index.min() <= offset_time <= df.index.max():
            closest = min(df.index, key=lambda x: abs(x - offset_time))
            return df.loc[closest, 'pressure']
        return pressure_current

    p_1h = get_pressure_at_offset(1)
    p_3h = get_pressure_at_offset(3)
    p_12h = get_pressure_at_offset(12)
    p_24h = get_pressure_at_offset(24)

    delta_1h = pressure_current - p_1h
    delta_3h = pressure_current - p_3h
    delta_12h = pressure_current - p_12h
    delta_24h = pressure_current - p_24h
    
    past_12h_df = df.loc[actual_target_time - timedelta(hours=12) : actual_target_time]
    min_12h = past_12h_df['pressure'].min() if not past_12h_df.empty else pressure_current
    
    trend = "安定"
    if delta_3h < -1.0: trend = "急降下"
    elif delta_3h < -0.3: trend = "下降中"
    elif delta_3h > 1.0: trend = "急上昇"
    elif delta_3h > 0.3: trend = "上昇中"

    return {
        "pressure_current": float(round(pressure_current, 2)),
        "pressure_delta_1h": float(round(delta_1h, 2)),
        "pressure_delta_3h": float(round(delta_3h, 2)),
        "pressure_delta_12h": float(round(delta_12h, 2)),
        "pressure_delta_24h": float(round(delta_24h, 2)),
        "pressure_min_12h": float(round(min_12h, 2)),
        "pressure_trend": trend
    }

# --- Helper Functions (Supabase CRUD) ---
def save_log_to_supabase(data):
    """Insert log data into Supabase."""
    try:
        main_columns = [
            'event_time', 'location_name', 'lat', 'lon', 'pain_level', 
            'factors', 'memo', 'pressure_current', 'pressure_delta_3h', 'pressure_trend'
        ]
        
        insert_data = {k: v for k, v in data.items() if k in main_columns}
        meta_data = {k: v for k, v in data.items() if k not in main_columns and k != 'datetime'}
        insert_data['meta_data'] = meta_data
        
        dt_obj = datetime.strptime(data['datetime'], '%Y-%m-%d %H:%M')
        insert_data['event_time'] = dt_obj.isoformat()

        response = supabase.table('headache_logs').insert(insert_data).execute()
        return True
    except Exception as e:
        st.error(f"Error saving to Supabase: {e}")
        return False

def get_logs_from_supabase():
    """Fetch all logs from Supabase."""
    try:
        response = supabase.table('headache_logs').select("*").order("event_time", desc=True).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['event_time'] = pd.to_datetime(df['event_time'])
            df['event_time'] = df['event_time'].dt.tz_convert(TIMEZONE)
        return df
    except Exception as e:
        st.error(f"Error fetching logs: {e}")
        return pd.DataFrame()

def delete_log_from_supabase(log_id):
    """Delete a log entry by ID."""
    try:
        supabase.table('headache_logs').delete().eq("id", log_id).execute()
        return True
    except Exception as e:
        st.error(f"Error deleting log: {e}")
        return False

# --- Analytics Functions ---
def render_dashboard(df_history):
    """
    分析ダッシュボードを描画する関数
    :param df_history: Supabaseから取得した履歴DataFrame
    """
    if df_history.empty:
        st.info("分析用のデータがまだありません。記録を追加してください。")
        return

    # 1. KPI カード
    st.markdown("### 📈 サマリー")
    kpi1, kpi2, kpi3 = st.columns(3)
    
    total_logs = len(df_history)
    avg_pain = df_history['pain_level'].mean()
    # 最大気圧低下: pressure_delta_3h の最小値 (例: -2.0 は -0.5 より小さい＝低下が大きい)
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
        hover_data=["event_time", "memo", "location_name"],
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
    df_heat['Weekday'] = df_heat['event_time'].dt.day_name()
    df_heat['Hour'] = df_heat['event_time'].dt.hour
    
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
    st.title("🌡️ HPL v2.0 (Supabase Edition)")
    
    config = load_config()

    # サイドバーに設定を移動
    with st.sidebar:
        st.header("⚙️ 設定")
        
        with st.expander("📍 場所設定"):
            with st.form("add_loc"):
                n = st.text_input("名前")
                la = st.number_input("緯度", value=35.6895, format="%.4f")
                lo = st.number_input("経度", value=139.6917, format="%.4f")
                if st.form_submit_button("追加"):
                    config["locations"].append({"name": n, "lat": la, "lon": lo})
                    save_config(config)
                    st.success(f"Added {n}")
                    st.rerun()
            
            rem_name = st.selectbox("削除対象", [l["name"] for l in config["locations"]], key="del_loc")
            if st.button("場所を削除"):
                config["locations"] = [l for l in config["locations"] if l["name"] != rem_name]
                save_config(config)
                st.success("Deleted")
                st.rerun()

        with st.expander("🏷️ 要因タグ設定"):
            curr = ", ".join(config.get("factor_options", []))
            new_txt = st.text_area("カンマ区切りで編集", curr)
            if st.button("タグを更新"):
                config["factor_options"] = [s.strip() for s in new_txt.split(",") if s.strip()]
                save_config(config)
                st.success("Updated")
                st.rerun()

    # メインタブ構成 (2タブ)
    tab_record, tab_analytics = st.tabs(["📝 記録入力", "📊 分析ダッシュボード"])
    
    # --- Tab 1: 記録 & 履歴 ---
    with tab_record:
        col_input, col_viz = st.columns([1, 2])
        
        with col_input:
            st.subheader("新規記録")
            
            # Inputs
            d = st.date_input("日付", datetime.now())
            t = st.time_input("時間", datetime.now().time())
            target_dt = datetime.combine(d, t)
            
            pain_level = st.slider("痛み (0-10)", 0, 10, 5)
            
            loc_names = [loc["name"] for loc in config["locations"]]
            def_idx = min(config.get("default_location_index", 0), len(loc_names)-1)
            sel_loc_name = st.selectbox("場所", loc_names, index=def_idx)
            sel_loc = next((l for l in config["locations"] if l["name"] == sel_loc_name), config["locations"][0])
            
            sel_factors = st.multiselect("要因", config.get("factor_options", []))
            memo = st.text_area("メモ", height=80)
            
            fetch_btn = st.button("気圧取得 & 分析", type="primary")

        # Session State for Analysis Result
        if 'analyzed_result' not in st.session_state:
            st.session_state['analyzed_result'] = None

        if fetch_btn:
            with st.spinner('Fetching weather data...'):
                df = get_pressure_data(sel_loc['lat'], sel_loc['lon'], target_dt)
                if df is not None:
                    feats = calculate_pressure_features(df, target_dt)
                    if feats:
                        st.session_state['analyzed_result'] = {
                            'df': df,
                            'features': feats,
                            'context': {
                                'dt': target_dt, 'loc': sel_loc, 
                                'pain': pain_level, 'factors': sel_factors, 'memo': memo
                            }
                        }

        # Visualization & Save
        with col_viz:
            if st.session_state['analyzed_result']:
                res = st.session_state['analyzed_result']
                feats = res['features']
                df_weather = res['df']
                ctx = res['context']
                
                # Metrics
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("気圧", f"{feats['pressure_current']} hPa", feats['pressure_trend'])
                m2.metric("3h変化", f"{feats['pressure_delta_3h']} hPa", delta_color="inverse")
                m3.metric("12h変化", f"{feats['pressure_delta_12h']} hPa", delta_color="inverse")
                m4.metric("12h最低", f"{feats['pressure_min_12h']} hPa")
                
                # Chart
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df_weather.index, y=df_weather['pressure'], mode='lines+markers', name='Pressure'))
                fig.add_vline(x=ctx['dt'], line_dash="dash", line_color="red")
                fig.add_annotation(x=ctx['dt'], y=1.02, yref="paper", text="Event", showarrow=False, font=dict(color="red"))
                fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20), title=f"{ctx['loc']['name']} の気圧推移")
                st.plotly_chart(fig, use_container_width=True)
                
                # Save Button
                if st.button("データベースに保存"):
                    # Prepare data dict
                    log_data = {
                        "datetime": ctx['dt'].strftime('%Y-%m-%d %H:%M'), # Temp string for logic
                        "lat": ctx['loc']['lat'],
                        "lon": ctx['loc']['lon'],
                        "location_name": ctx['loc']['name'],
                        "pain_level": ctx['pain'],
                        "factors": ctx['factors'], # List
                        "memo": ctx['memo'],
                        **feats
                    }
                    
                    if save_log_to_supabase(log_data):
                        st.success("Saved to Supabase!")
                        st.session_state['analyzed_result'] = None # Reset
                        st.rerun()

        # History List
        st.divider()
        st.subheader("📜 履歴管理")
        
        history_df = get_logs_from_supabase()
        if not history_df.empty:
            # Add Delete Column
            history_df['Delete'] = False
            
            # Display needed columns only
            display_cols = ['Delete', 'event_time', 'location_name', 'pain_level', 'pressure_delta_3h', 'pressure_trend', 'factors', 'memo']
            
            # Format datetime for display
            display_df = history_df.copy()
            display_df['event_time'] = display_df['event_time'].dt.strftime('%Y-%m-%d %H:%M')
            
            edited_df = st.data_editor(
                display_df[display_cols],
                hide_index=True,
                column_config={
                    "Delete": st.column_config.CheckboxColumn("削除", width="small"),
                    "event_time": "日時",
                    "location_name": "場所",
                    "pain_level": st.column_config.NumberColumn("痛み", format="%d"),
                    "pressure_delta_3h": "3h変化",
                    "pressure_trend": "傾向",
                    "factors": st.column_config.ListColumn("要因"),
                    "memo": "メモ"
                }
            )
            
            if st.button("選択したログを削除"):
                to_delete_indices = edited_df[edited_df['Delete']].index
                if not to_delete_indices.empty:
                    # Map back to original IDs
                    ids_to_delete = history_df.loc[to_delete_indices, 'id'].tolist()
                    for log_id in ids_to_delete:
                        delete_log_from_supabase(log_id)
                    st.success(f"Deleted {len(ids_to_delete)} logs.")
                    st.rerun()
        else:
            st.info("データがありません。")

    # --- Tab 2: 分析ダッシュボード ---
    with tab_analytics:
        st.header("📊 統計ダッシュボード")
        df_logs = get_logs_from_supabase()
        render_dashboard(df_logs)

if __name__ == "__main__":
    main()