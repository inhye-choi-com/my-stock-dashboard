import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import io
from streamlit_autorefresh import st_autorefresh
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# 1. 페이지 기본 설정
st.set_page_config(page_title="실시간 주도주 단타 매매 대시보드", layout="wide")

# 상승/하락 색상 및 추천 종목 음영 스타일 정의
st.markdown("""
<style>
    .up-color { color: #ef4444; font-weight: bold; }   
    .down-color { color: #3b82f6; font-weight: bold; } 
    .flat-color { color: #6b7280; }                   
    /* 추천 종목 하이라이트 배경 (연한 노란색) */
    .recommend-row { background-color: #fef08a !important; font-weight: bold; }
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

# 3. 네이버 증권 데이터 추출 함수
@st.cache_data(ttl=10)
def fetch_market_data(sosok_code):
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
    # 순수 숫자형태의 거래대금 원본 저장 (추천 로직용)
    df_v['raw_val'] = pd.to_numeric(df_v['거래대금'], errors='coerce')
    df_v['거래대금(억)'] = (df_v['raw_val'] / 1000).round(1)
    
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
    # 순수 숫자형태의 거래량 원본 저장 (추천 로직용)
    df_g['raw_vol'] = pd.to_numeric(df_g['거래량'], errors='coerce')
    df_g['거래량(만)'] = (df_g['raw_vol'] / 10000).round(1)
    
    return df_v, df_g

# 캔들 + 거래량 + 이평선 종합 차트 함수
def get_stock_chart(code, name, period_choice, market_type):
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
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                            vertical_spacing=0.05, row_width=[0.25, 0.75])
        
        fig.add_trace(go.Candlestick(
            x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            name="주가", increasing_line_color='#ef4444', decreasing_line_color='#3b82f6'
        ), row=1, col=1)
        
        fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='#ff9800', width=1.5), name='5일선'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA10'], line=dict(color='#4caf50', width=1.5), name='10일선'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#9c27b0', width=1.5), name='20일선'), row=1, col=1)
        
        colors = ['#ef4444' if row['Close'] >= row['Open'] else '#3b82f6' for _, row in df.iterrows()]
        fig.add_trace(go.Bar(
            x=df.index, y=df['Volume'], name="거래량", marker_color=colors
        ), row=2, col=1)
        
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            margin=dict(l=10, r=10, t=10, b=10),
            height=450,
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("데이터가 없거나 종목 코드가 올바르지 않습니다.")

# 등락률 문자열을 숫자로 변환하는 보조 함수
def parse_rate(val_str):
    try:
        return float(str(val_str).replace('%','').replace('+','').strip())
    except:
        return 0.0

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

market_tab = st.radio("📈 시장 선택", ["코스피 (KOSPI)", "코스닥 (KOSDAQ)"], horizontal=True)
sosok_code = 0 if market_tab == "코스피 (KOSPI)" else 1

try:
    df_v, df_g = fetch_market_data(sosok_code)
    
    # 추천 종목 및 이유 저장을 위한 딕셔너리
    recommendations = {}
    
    # ------------------ HTML 테이블 빌더 (음영 로직 포함) ------------------
    def build_custom_html_table(df, table_type):
        html = "<table style='width:100%; border-collapse:collapse;'>"
        # 헤더 생성
        if table_type == "value":
            html += "<tr style='border-bottom:2px solid #ddd; text-align:left;'><th>순위</th><th>종목명</th><th>등락률</th><th>거래대금(억)</th></tr>"
        else:
            html += "<tr style='border-bottom:2px solid #ddd; text-align:left;'><th>순위</th><th>종목명</th><th>등락률</th><th>거래량(만)</th></tr>"
        
        for idx, row in df.iterrows():
            rank = idx + 1
            name = row['종목명']
            rate_num = parse_rate(row['등락률'])
            
            # 등락률 컬러 포맷팅
            if rate_num > 0: rate_html = f"<span class='up-color'>▲ +{rate_num}%</span>"
            elif rate_num < 0: rate_html = f"<span class='down-color'>▼ {rate_num}%</span>"
            else: rate_html = f"<span class='flat-color'>0.0%</span>"
            
            # [단타 매매 추천 알고리즘 및 음영 판단]
            is_recommended = False
            row_class = ""
            
            if table_type == "value":
                # 조건 1: 거래대금이 500억 이상 터지면서 과열권(15%이하) 전 단계인 주도주
                if row['거래대금(억)'] >= 500 and 3 <= rate_num <= 15:
                    is_recommended = True
                    recommendations[name] = f"💰 **[거래대금 주도주 포착]** 현재 당일 거래대금이 **{row['거래대금(억)']}억** 돌파하며 시장의 돈을 흡수하고 있습니다. 등락률 **+{rate_num}%**로 상승 초입 또는 안정적인 돌파 구간이므로 분봉상 눌림목 지지를 확인 후 진입하기 유리합니다."
            else:
                # 조건 2: 거래량이 100만 주 이상 폭발하며 강하게 고개를 든 급등주
                if row['raw_vol'] >= 1000000 and rate_num >= 7:
                    is_recommended = True
                    recommendations[name] = f"🚀 **[거래량 폭발 급등주 탐지]** 당일 누적 거래량 **{row['거래량(만)']}만 주**를 기록하며 직전 저항대를 강하게 돌파하고 있습니다. 등락률 **+{rate_num}%**의 강한 수급이 확인되므로, 1분봉상 이평선 이격이 과도하게 벌어지지 않았는지 체크 후 추격/돌파 매매 타점을 잡을 수 있습니다."
            
            if is_recommended:
                row_class = "class='recommend-row'"
            
            # 테이블 행 조립
            if table_type == "value":
                html += f"<tr {row_class} style='border-bottom:1px solid #eee; height:35px;'><td>{rank}</td><td>{name}</td><td>{rate_html}</td><td>{row['거래대금(억)']}</td></tr>"
            else:
                html += f"<tr {row_class} style='border-bottom:1px solid #eee; height:35px;'><td>{rank}</td><td>{name}</td><td>{rate_html}</td><td>{row['거래량(만)']}</td></tr>"
                
        html += "</table>"
        return html

    # -------------------------------------------------------------------
    
    # 종목 선택 리스트 조합
    combined_list = pd.concat([df_v[['종목명', '코드']], df_g[['종목명', '코드']]]).drop_duplicates('종목명')
    stock_names = combined_list['종목명'].tolist()

    col1, col2, col3 = st.columns([1, 1, 1.6])
    
    with col1:
        st.subheader("💵 거래대금 상위 Top 10")
        st.markdown(build_custom_html_table(df_v.reset_index(drop=True), "value"), unsafe_allow_html=True)
        
    with col2:
        st.subheader("🔥 당일 급등주 Top 10")
        st.markdown(build_custom_html_table(df_g.reset_index(drop=True), "volume"), unsafe_allow_html=True)
        
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
        
        # ------------------ [신규] 실전 단타 추천 코멘트 영역 ------------------
        st.markdown("---")
        st.subheader("🤖 AI 단타 실시간 매매 코멘트")
        
        if selected_stock_name in recommendations:
            st.info(recommendations[selected_stock_name])
        else:
            st.markdown(f"ℹ️ **{selected_stock_name}** 종목은 현재 시스템이 지정한 실시간 고승률 단타 추천 조건(거래대금 500억 이상 및 상승초입 또는 100만주 이상 대량거래 돌파)에는 도달하지 않았습니다. 차트상의 이평선 지지여부를 개별적으로 체크하세요.")
        # -------------------------------------------------------------------

except Exception as e:
    st.error(f"오류 발생: {e}")
