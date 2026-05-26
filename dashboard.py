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
st.set_page_config(page_title="실시간 주도주 & 포트폴리오 패널", layout="wide")

# [연동 완료] 제공해주신 구글 스프레드시트 공유 주소
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1pMpXBZh3sIDE79e7vNmUgdVEU8f-qbywYy7biuWoUNM/edit?usp=sharing"

# 상승/하락/추천 및 포트폴리오 감시 스타일 정의
st.markdown("""
<style>
    .up-color { color: #ef4444; font-weight: bold; }   
    .down-color { color: #3b82f6; font-weight: bold; } 
    .flat-color { color: #6b7280; }                   
    .recommend-row { background-color: #fef08a !important; font-weight: bold; }
    
    /* 포트폴리오 감시용 음영 색상 */
    .portfolio-danger { background-color: #fee2e2 !important; color: #b91c1c !important; font-weight: bold; } /* -2% 이하 (연한 빨강 배경/진한 빨강 글씨) */
    .portfolio-success { background-color: #dcfce7 !important; color: #15803d !important; font-weight: bold; } /* +4% 이상 (연한 초록 배경/진한 초록 글씨) */
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

# 구글 스프레드시트에서 보유 현황 읽어오는 함수
def load_portfolio_from_sheets(url):
    try:
        if "/edit" in url:
            base_url = url.split("/edit")[0]
            csv_url = base_url + "/export?format=csv"
        else:
            csv_url = url
        df = pd.read_csv(csv_url)
        return df
    except Exception as e:
        st.sidebar.error(f"구글 시트 연동 실패: {e}")
        return pd.DataFrame(columns=["종목명", "매수가", "시장"])

# 3. 네이버 증권 데이터 추출 함수
@st.cache_data(ttl=10)
def fetch_market_data(sosok_code):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
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
    df_v['raw_val'] = pd.to_numeric(df_v['거래대금'], errors='coerce')
    df_v['거래대금(억)'] = (df_v['raw_val'] / 1000).round(1)
    
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
    df_g['raw_vol'] = pd.to_numeric(df_g['거래량'], errors='coerce')
    df_g['거래량(만)'] = (df_g['raw_vol'] / 10000).round(1)
    
    return df_v, df_g

# 개별 종목 현재가만 빠르게 가져오는 함수 (포트폴리오용)
def get_current_price(code, market_type):
    suffix = ".KS" if "코스피" in market_type else ".KQ"
    try:
        ticker = yf.Ticker(f"{code}{suffix}")
        todays_data = ticker.history(period="1d")
        if not todays_data.empty:
            return int(todays_data['Close'].iloc[-1])
    except:
        pass
    return None

# 전 종목 코드 마스터 데이터를 만들기 위한 네이버 종목-코드 딕셔너리 생성기
@st.cache_data(ttl=3600)
def get_all_stock_codes():
    mapping = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for sosok in [0, 1]:
        url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        for anchor in soup.find_all('a', {'class': 'tltle'}):
            mapping[anchor.get_text().strip()] = anchor['href'].split('=')[-1]
    return mapping

# 캔들 + 거래량 + 이평선 종합 차트 함수
def get_stock_chart(code, name, period_choice, market_type):
    suffix = ".KS" if "코스피" in market_type else ".KQ"
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
            x=df.index, y=df['Volume'],
