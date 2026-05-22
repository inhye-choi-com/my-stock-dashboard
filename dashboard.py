import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import io
from streamlit_autorefresh import st_autorefresh

# 1. 페이지 기본 설정
st.set_page_config(page_title="My 실시간 단타 대시보드", layout="wide")

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
    current_hour = now.hour
    current_minute = now.minute
    is_weekday = now.weekday() < 5
    is_market_open = is_weekday and (9 <= current_hour < 15 or (current_hour == 15 and current_minute <= 30))
    
    if is_market_open:
        display_time = now.strftime("%H:%M:%S")
    elif is_weekday and (current_hour > 15 or (current_hour == 15 and current_minute > 30)):
        display_time = "15:30 (장마감 최종 데이터 고정)"
    else:
        display_time = "09:00 (이전 영업일 마감 데이터)"
    return display_time, is_market_open

# 3. 네이버 증권 크롤링 함수
@st.cache_data(ttl=10)
def fetch_real_market_data():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    # --- A. 거래대금 상위 (코스피) ---
    url_value = "https://finance.naver.com/sise/sise_quant.naver?sosok=0"
    res_value = requests.get(url_value, headers=headers, timeout=10)
    soup_value = BeautifulSoup(res_value.text, 'html.parser')
    table_value = soup_value.find('table', {'class': 'type_2'})
    
    df_list_v = pd.read_html(io.StringIO(str(table_value)))[0]
    df_list_v = df_list_v.dropna(subset=['종목명'])
    df_list_v = df_list_v[df_list_v['종목명'] != '종목명']
    df_value_raw = df_list_v.head(10).copy()
    
    # 거래대금 컬럼 안전하게 처리
    if '거래대금' in df_value_raw.columns:
        df_value_raw['거래대금'] = pd.to_numeric(df_value_raw['거래대금'], errors='coerce')
        df_value_raw['거래대금(억)'] = (df_value_raw['거래대금'] / 1000).round(1)
        df_value_final = df_value_raw[['종목명', '등락률', '거래대금(억)']].copy()
    else:
        df_value_final = df_value_raw[['종목명', '등락률']].copy()
        df_value_final['거래대금(억)'] = "N/A"
        
    df_value_final.insert(0, '순위', range(1, len(df_value_final) + 1))
    
    # --- B. 등락률 상위 (급등주) ---
    url_gain = "https://finance.naver.com/sise/sise_rise.naver?sosok=0"
    res_gain = requests.get(url_gain, headers=headers, timeout=10)
    soup_gain = BeautifulSoup(res_gain.text, 'html.parser')
    table_gain = soup_gain.find('table', {'class': 'type_2'})
    
    df_list_g = pd.read_html(io.StringIO(str(table_gain)))[0]
    df_list_g = df_list_g.dropna(subset=['종목명'])
    df_list_g = df_list_g[df_list_g['종목명'] != '종목명']
    df_gain_raw = df_list_g.head(10).copy()
    
    # 등락률 상위 페이지는 '거래량' 컬럼에 맞춰 안전하게 추출
    if '거래량' in df_gain_raw.columns:
        df_gain_raw['거래량'] = pd.to_numeric(df_gain_raw['거래량'], errors='coerce')
        df_gain_raw['거래량(만주)'] = (df_gain_raw['거래량'] / 10000).round(1)
        df_gain_final = df_gain_raw[['종목명', '등락률', '거래량(만주)']].copy()
    else:
        df_gain_final = df_gain_raw[['종목명', '등락률']].copy()
        
    df_gain_final.insert(0, '순위', range(1, len(df_gain_final) + 1))
    
    # --- C. 주요 뉴스 ---
    url_news = "https://finance.naver.
