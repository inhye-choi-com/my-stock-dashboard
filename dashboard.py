import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import io
from streamlit_autorefresh import st_autorefresh
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots  # 캔들과 거래량을 같이 그리기 위한 도구

# 1. 페이지 기본 설정
st.set_page_config(page_title="실시간 주도주 단타 매매 대시보드", layout="wide")

# 상승/하락 색상 스타일
st.markdown("""
<style>
    .up-color { color: #ef4444; font-weight: bold; }   
    .down-color { color: #3b82f6; font-weight: bold; } 
    .flat-color { color: #6b7280; }                   
</style>
""", unsafe_allow_html=True)

# 2. 시간 계산 로직
def get_current_market_time():
    now = datetime.now()
    is_weekday = now.weekday() < 5
    current_hour = now.hour
    current_minute = now.minute
    is_market_open = is_weekday and (9 <= current_hour < 15 or (current_hour == 15 and current_minute <= 30))
    
    if is_market_open:
        display_time = now.strftime("%H:%M:%S")
    elif is_weekday and (current_hour > 15 or (current_hour == 15 and current_minute > 30)):
        display_time = "15:30 (장마감)"
    else:
        display_time = "09:00 (장 시작 전)"
    return display_time, is_market_open

# 3. 네이버 증권 데이터 추출 함수 (코스피/코스닥 선택 가능하도록 개선)
@st.cache_data(ttl=10)
def fetch_market_data(sosok_code):
    # sosok_code: 코스피는 0, 코스닥은 1
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    # --- A. 거래대금 상위 ---
    url_v = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok_code}"
    res_v = requests.get(url_v, headers=headers, timeout=10)
    soup_v = BeautifulSoup(res_v.text, 'html.parser')
    table_v = soup_v.find('table', {'class': 'type_2'})
    
    stocks = []
    rows = table_v.find_all('tr')
    for row in rows:
        anchor = row.find('a', {'class': 'tltle'})
        if anchor:
            stocks.append({'종목명': anchor.get_text(), '코드': anchor['href'].split('=')[-1]})
            
    df_v = pd.read_html(io.StringIO(str(table_v)))[0]
    df_v = df_v.dropna(subset=['종목명'])
    df_v = df_v[df_v['종목명'] != '종목명'].head(10).copy()
    
    df_v['코드'] = [s['코드'] for s in stocks[:10]]
    df_v['거래대금(억)'] = (pd.to_numeric(df_v['거래대금'], errors='coerce') / 1000).round(1)
    df_v_final = df_v[['종목명', '등락률', '거래대금(억)', '코드']].copy()
    df_v_final.insert(0, '순위', range(1, len(df_v_final) + 1))
    
    # --- B. 등락률 상위 ---
    url_g = f"https://finance.naver.com/sise/sise_rise.naver?sosok={sosok_code}"
    res_g = requests.get(url_g, headers=headers, timeout=10)
    soup_g = BeautifulSoup(res_g.text, 'html.parser')
    table_g = soup_g.find('table', {'class': 'type_2'})
    
    stocks_g = []
    rows_g = table_g.find_all('tr')
    for row in rows_g:
        anchor = row.find('a', {'class': 'tltle'})
        if anchor:
            stocks_g.append({'종목명': anchor.get_text(), '코드': anchor['href'].split('=')[-1]})
            
    df_g = pd.read_html(io.StringIO(str(table_g)))[0]
    df_g = df_g.dropna(subset=['종목명'])
    df_g = df_g[df_g['종목명'] != '종목명'].head(10).copy()
    
    df_g['코드'] = [s['코드'] for s in stocks_g[:10]]
    df_g['거래량(만)'] = (pd.to_numeric(df_g['거래량'], errors='coerce') / 10000).round(1)
    df_g_final = df_g[['종목명', '등락률', '거래량(만)', '코드']].copy()
    df_g_final.insert(0, '순위', range(1, len(df_g_final) + 1))
    
    return df_v_final, df_g_final

# [대폭강화] 캔들 + 거래량 + 이평선 종합 차트 함수
def get_stock_chart(code, name, period_choice, market_type):
    # 코스피는 .KS, 코스닥은 .KQ 가 뒤에 붙어야 함
    suffix = ".KS" if market_type == "코스피 (KOSPI)" else ".KQ"
    full_code = f"{code}{suffix}"
    ticker = yf.Ticker(full_code)
    
    if period_choice == "하루 (1분봉)":
        period_val, interval_val = "1d", "1m"
    elif period_choice == "일주일 (30분봉)":
        period_val, interval_val = "5d", "30m"
    else:
        period_val, interval_val = "1mo", "1d"
        
    df = ticker.history(period=period_val, interval=interval_val)
    
    if df.empty and period_choice == "하루 (1분봉)":
        df = ticker.history(period="5d", interval="30m")
        st.info("💡 장 시작 직후에는 분봉 데이터가 부족하여 일주일 차트로 대체 표시합니다.")
    
    if not df.empty:
        # 단타용 이동평균선 계산 (5선, 10선, 20선)
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()

        # 차트 영역을 위(캔들, 75%)와 아래(거래량, 25%)로 분할
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                            vertical_spacing=0.05, row_width=[0.25, 0.75])
        
        # 1. 캔들차트 추가 (1행)
        fig.add_trace(go.Candlestick(
            x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            name="주가", increasing_line_color='#ef4444', decreasing_line_color='#3b82f6'
        ), row=1, col=1)
        
        # 2. 이동평균선 추가 (1행)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='#ff9800', width=1.5), name='5일선'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA10'], line=dict(color='#4caf50', width=1.5), name='10일선'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#9c27b0', width=1.5), name='20일선'), row=1, col=1)
        
        # 3. 거래량 막대그래프 추가 (2행)
        # 전 봉 대비 상승 시 빨강, 하락 시 파랑 색상 부여
        colors = ['#ef4444' if row['Close'] >= row['Open'] else '#3b82f6' for _, row in df.iterrows()]
        fig.add_trace(go.Bar(
            x=df.index, y=df['Volume'], name="거래량", marker_color=colors
        ), row=2, col=1)
        
        # 레이아웃 정돈
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            margin=dict(l=10, r=10, t=10, b=10),
            height=500,
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("데이터가 없거나 종목 코드가 올바르지 않습니다.")

# 4. UI 렌더링
display_time, is_market_open = get_current_market_time()

if is_market_open:
    st_autorefresh(interval=60000, key="datarefresh")

st.title("🔥 실시간 단타 매매 주도주 패널")
st.caption(f"📅 기준일: {datetime.now().strftime('%Y-%m-%d')} | 🔄 60초 간격 자동 실시간 동기화")

if is_market_open:
    st.success(f"📌 **시장 작동 중 - 데이터 동기화:** {display_time}")
else:
    st.warning(f"⚠️ 현재 장 마감 상태입니다. ({display_time})")

# [기능 확장] 코스피 / 코스닥 선택 탭 추가!
market_tab = st.radio("📈 시장 선택", ["코스피 (KOSPI)", "코스닥 (KOSDAQ)"], horizontal=True)
sosok_code = 0 if market_tab == "코스피 (KOSPI)" else 1

try:
    df_v, df_g = fetch_market_data(sosok_code)
    
    # 대시보드 연동용 종목 조합
    combined_list = pd.concat([df_v[['종목명', '코드']], df_g[['종목명', '코드']]]).drop_duplicates('종목명')
    stock_names = combined_list['종목명'].tolist()
    
    df_v_display = df_v.copy()
    df_g_display = df_g.copy()
    
    def format_rate(val):
        val_str = str(val).replace('%','').replace('+','')
        try:
            num = float(val_str)
            if num > 0: return f"<span class='up-color'>▲ +{num}%</span>"
            elif num < 0: return f"<span class='down-color'>▼ {num}%</span>"
            return f"<span>0.0%</span>"
        except: return val

    df_v_display['등락률'] = df_v_display['등락률'].apply(format_rate)
    df_g_display['등락률'] = df_g_display['등락률'].apply(format_rate)

    col1, col2, col3 = st.columns([1, 1, 1.6])
    
    with col1:
        st.subheader("💵 거래대금 상위 Top 10")
        st.markdown(df_v_display.drop(columns=['코드']).set_index("순위").to_html(escape=False), unsafe_allow_html=True)
        
    with col2:
        st.subheader("🔥 당일 급등주 Top 10")
        st.markdown(df_g_display.drop(columns=['코드']).set_index("순위").to_html(escape=False), unsafe_allow_html=True)
        
    with col3:
        st.subheader("🔍 주도주 연동 멀티 차트")
        selected_stock_name = st.selectbox("분석할 주도주를 선택하세요", stock_names, index=0)
        
        period_choice = st.radio(
            "차트 주기", 
            ["하루 (1분봉)", "일주일 (30분봉)", "한달 (일봉)"], 
            horizontal=True
        )
        
        selected_code = combined_list[combined_list['종목명'] == selected_stock_name]['코드'].values[0]
        st.markdown(f"### 📊 {selected_stock_name} ({selected_code})")
        get_stock_chart(selected_code, selected_stock_name, period_choice, market_tab)

except Exception as e:
    st.error(f"오류 발생: {e}")
