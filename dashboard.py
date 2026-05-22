import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import io
from streamlit_autorefresh import st_autorefresh
import yfinance as yf  # 그래프 데이터를 위한 라이브러리 추가

# 1. 페이지 기본 설정
st.set_page_config(page_title="실시간 주도주 차트 대시보드", layout="wide")

# 상승/하락 색상 강조 스타일
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

# 3. 네이버 증권 데이터 및 종목코드 추출 함수
@st.cache_data(ttl=10)
def fetch_market_data():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    # --- A. 거래대금 상위 (코스피) ---
    url_v = "https://finance.naver.com/sise/sise_quant.naver?sosok=0"
    res_v = requests.get(url_v, headers=headers, timeout=10)
    soup_v = BeautifulSoup(res_v.text, 'html.parser')
    table_v = soup_v.find('table', {'class': 'type_2'})
    
    # 종목명과 종목코드를 같이 추출
    stocks = []
    rows = table_v.find_all('tr')
    for row in rows:
        anchor = row.find('a', {'class': 'tltle'})
        if anchor:
            name = anchor.get_text()
            code = anchor['href'].split('=')[-1]
            stocks.append({'종목명': name, '코드': code})
            
    df_v = pd.read_html(io.StringIO(str(table_v)))[0]
    df_v = df_v.dropna(subset=['종목명'])
    df_v = df_v[df_v['종목명'] != '종목명'].head(10).copy()
    
    # 코드 정보 합치기
    df_v['코드'] = [s['코드'] for s in stocks[:10]]
    df_v['거래대금(억)'] = (pd.to_numeric(df_v['거래대금'], errors='coerce') / 1000).round(1)
    df_v_final = df_v[['종목명', '등락률', '거래대금(억)', '코드']].copy()
    df_v_final.insert(0, '순위', range(1, len(df_v_final) + 1))
    
    # --- B. 등락률 상위 (급등주) ---
    url_g = "https://finance.naver.com/sise/sise_rise.naver?sosok=0"
    res_g = requests.get(url_g, headers=headers, timeout=10)
    soup_g = BeautifulSoup(res_g.text, 'html.parser')
    table_g = soup_g.find('table', {'class': 'type_2'})
    
    stocks_g = []
    rows_g = table_g.find_all('tr')
    for row in rows_g:
        anchor = row.find('a', {'class': 'tltle'})
        if anchor:
            name = anchor.get_text()
            code = anchor['href'].split('=')[-1]
            stocks_g.append({'종목명': name, '코드': code})
            
    df_g = pd.read_html(io.StringIO(str(table_g)))[0]
    df_g = df_g.dropna(subset=['종목명'])
    df_g = df_g[df_g['종목명'] != '종목명'].head(10).copy()
    
    df_g['코드'] = [s['코드'] for s in stocks_g[:10]]
    df_g['거래량(만)'] = (pd.to_numeric(df_g['거래량'], errors='coerce') / 10000).round(1)
    df_g_final = df_g[['종목명', '등락률', '거래량(만)', '코드']].copy()
    df_g_final.insert(0, '순위', range(1, len(df_g_final) + 1))
    
    return df_v_final, df_g_final

# 주가 차트 가져오기 함수
def get_stock_chart(code, name):
    # 한국 종목 코드는 끝에 .KS(코스피) 또는 .KQ(코스닥)가 붙어야 함 (여기선 코스피 기준)
    full_code = f"{code}.KS"
    ticker = yf.Ticker(full_code)
    # 오늘 하루치 분봉 데이터를 가져오기 (1분 단위)
    df = ticker.history(period="1d", interval="1m")
    
    if df.empty:
        # 분봉 데이터가 없으면 최근 5일치 일봉 데이터 시도
        df = ticker.history(period="5d")
    
    if not df.empty:
        st.subheader(f"📊 {name} ({code}) 실시간 흐름")
        st.line_chart(df['Close'])
    else:
        st.error("차트 데이터를 불러올 수 없습니다. (종목코드 확인 필요)")

# 4. UI 렌더링
display_time, is_market_open = get_current_market_time()

if is_market_open:
    st_autorefresh(interval=60000, key="datarefresh")

st.title("🚀 주식 주도주 실시간 차트 대시보드")
st.caption(f"📅 기준일: {datetime.now().strftime('%Y-%m-%d')} | 🔄 60초 간격 자동 갱신")

if is_market_open:
    st.success(f"📌 **현재 데이터 동기화 시점:** {display_time}")
else:
    st.warning(f"⚠️ 현재 장 마감 상태입니다. ({display_time})")

try:
    df_v, df_g = fetch_market_data()
    
    # 종목 선택 리스트 만들기 (거래대금 상위 + 등락률 상위)
    combined_list = pd.concat([df_v[['종목명', '코드']], df_g[['종목명', '코드']]]).drop_duplicates('종목명')
    stock_names = combined_list['종목명'].tolist()
    
    # 좌측/중앙 표 시각화용 포맷팅
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

    # 화면 분할
    col1, col2, col3 = st.columns([1, 1, 1.5])
    
    with col1:
        st.subheader("💵 거래대금 상위")
        st.markdown(df_v_display.drop(columns=['코드']).set_index("순위").to_html(escape=False), unsafe_allow_html=True)
        
    with col2:
        st.subheader("🔥 등락률 상위")
        st.markdown(df_g_display.drop(columns=['코드']).set_index("순위").to_html(escape=False), unsafe_allow_html=True)
        
    with col3:
        st.subheader("🔍 종목 상세 차트")
        # 기본 선택을 거래대금 1위 종목으로 설정
        selected_stock_name = st.selectbox("그래프를 볼 종목을 선택하세요", stock_names, index=0)
        
        # 선택된 종목의 코드 찾기
        selected_code = combined_list[combined_list['종목명'] == selected_stock_name]['코드'].values[0]
        
        # 차트 그리기
        get_stock_chart(selected_code, selected_stock_name)

except Exception as e:
    st.error(f"오류 발생: {e}")
