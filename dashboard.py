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
    .portfolio-danger { background-color: #fee2e2 !important; color: #b91c1c !important; font-weight: bold; } 
    .portfolio-success { background-color: #dcfce7 !important; color: #15803d !important; font-weight: bold; } 
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
        return pd.DataFrame(columns=["종목명", "매수가", "보유주수", "시장"])

# 3. 네이버 증권 데이터 추출 함수
@st.cache_data(ttl=10)
def fetch_market_data(sosok_code):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    # 거래대금 상위
    url_v = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok_code}"
    res_v = requests.get(url_v, headers=headers, timeout=10)
    soup_v = BeautifulSoup(res_v.text, 'html.parser')
    table_v = soup_v.find('table', {'class': 'type_2'})
    
    stocks = []
    rows = table_v.find_all('tr')
    for row in rows:
        anchor = row.find('a', {'class': 'tltle'})
        if anchor:
            stocks.append({'종목명': anchor.get_text().strip(), '코드': anchor['href'].split('=')[-1]})
            
    df_v = pd.read_html(io.StringIO(str(table_v)))[0]
    df_v = df_v.dropna(subset=['종목명'])
    df_v = df_v[df_v['종목명'] != '종목명'].head(10).copy()
    
    actual_len_v = min(len(df_v), len(stocks))
    df_v = df_v.head(actual_len_v).copy()
    df_v['코드'] = [s['코드'] for s in stocks[:actual_len_v]]
    
    df_v['raw_val'] = pd.to_numeric(df_v['거래대금'], errors='coerce').fillna(0)
    df_v['거래대금(억)'] = (df_v['raw_val'] / 1000).round(1)
    
    # 등락률 상위
    url_g = f"https://finance.naver.com/sise/sise_rise.naver?sosok={sosok_code}"
    res_g = requests.get(url_g, headers=headers, timeout=10)
    soup_g = BeautifulSoup(res_g.text, 'html.parser')
    table_g = soup_g.find('table', {'class': 'type_2'})
    
    stocks_g = []
    rows_g = table_g.find_all('tr')
    for row in rows_g:
        anchor = row.find('a', {'class': 'tltle'})
        if anchor:
            stocks_g.append({'종목명': anchor.get_text().strip(), '코드': anchor['href'].split('=')[-1]})
            
    df_g = pd.read_html(io.StringIO(str(table_g)))[0]
    df_g = df_g.dropna(subset=['종목명'])
    df_g = df_g[df_g['종목명'] != '종목명'].head(10).copy()
    
    actual_len_g = min(len(df_g), len(stocks_g))
    df_g = df_g.head(actual_len_g).copy()
    df_g['코드'] = [s['코드'] for s in stocks_g[:actual_len_g]]
    
    df_g['raw_vol'] = pd.to_numeric(df_g['거래량'], errors='coerce').fillna(0)
    df_g['거래량(만)'] = (df_g['raw_vol'] / 10000).round(1)
    
    return df_v, df_g

# 개별 종목 현재가 가져오기 함수
def get_current_price(code, market_type):
    suffix = ".KS" if "코스피" in str(market_type) else ".KQ"
    try:
        ticker = yf.Ticker(f"{code}{suffix}")
        todays_data = ticker.history(period="1d")
        if not todays_data.empty:
            return int(todays_data['Close'].iloc[-1])
    except:
        pass
    return None

# 전 종목 코드 마스터 딕셔너리 구축
@st.cache_data(ttl=3600)
def get_all_stock_codes():
    mapping = {}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    for sosok in [0, 1]:
        url = f"https://finance.naver.com/sise/sise_quant.naver?sosok={sosok}"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            for anchor in soup.find_all('a', {'class': 'tltle'}):
                stock_name = anchor.get_text().strip()
                stock_code = anchor['href'].split('=')[-1]
                mapping[stock_name] = stock_code
        except:
            pass
    return mapping

# 캔들 + 거래량 + 이평선 종합 차트 함수
def get_stock_chart(code, name, period_choice, market_type):
    suffix = ".KS" if "코스피" in str(market_type) else ".KQ"
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
            x=df.index, y=df['Volume'], name="거래량", marker_color=colors
        ), row=2, col=1)
        
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            margin=dict(l=10, r=10, t=10, b=10),
            height=400,
            template="plotly_white",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)

def parse_rate(val_str):
    try:
        return float(str(val_str).replace('%','').replace('+','').strip())
    except:
        return 0.0

# 4. UI 렌더링
display_time, is_market_open = get_current_market_time()

if is_market_open:
    st_autorefresh(interval=60000, key="datarefresh")

st.title("🔥 실시간 단타 매매 & 스마트 포트폴리오")
st.caption(f"📅 기준일: {datetime.now().strftime('%Y-%m
