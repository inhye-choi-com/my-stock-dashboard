import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time

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
        display_minute = "30" if current_minute >= 30 else "00"
        display_time = f"{current_hour}:{display_minute}"
    elif is_weekday and (current_hour > 15 or (current_hour == 15 and current_minute > 30)):
        display_time = "15:30 (장마감 최종 데이터 고정)"
    else:
        display_time = "09:00 (이전 영업일 마감 데이터)"
    return display_time, is_market_open

# 3. 네이버 증권 크롤링 함수 (클라우드 환경 표준형)
@st.cache_data(ttl=60)  # 클라우드에서는 1분 단위로 따끈따끈하게 갱신
def fetch_real_market_data():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    # A. 거래대금 상위
    url_value = "https://finance.naver.com/sise/sise_quant.naver?sosok=0"
    res_value = requests.get(url_value, headers=headers, timeout=10)
    soup_value = BeautifulSoup(res_value.text, 'html.parser')
    table_value = soup_value.find('table', {'class': 'type_2'})
    df_list_v = pd.read_html(str(table_value))[0]
    df_list_v = df_list_v.dropna(subset=['종목명'])
    df_list_v = df_list_v[df_list_v['종목명'] != '종목명']
    df_value_raw = df_list_v.head(10).copy()
    df_value_raw['거래대금'] = pd.to_numeric(df_value_raw['거래대금'], errors='coerce')
    df_value_raw['거래대금(억)'] = (df_value_raw['거래대금'] / 100).round(1)
    df_value_final = df_value_raw[['종목명', '등락률', '거래대금(억)']].copy()
    df_value_final.insert(0, '순위', range(1, len(df_value_final) + 1))
    
    # B. 등락률 상위
    url_gain = "https://finance.naver.com/sise/sise_rise.naver?sosok=0"
    res_gain = requests.get(url_gain, headers=headers, timeout=10)
    soup_gain = BeautifulSoup(res_gain.text, 'html.parser')
    table_gain = soup_gain.find('table', {'class': 'type_2'})
    df_list_g = pd.read_html(str(table_gain))[0]
    df_list_g = df_list_g.dropna(subset=['종목명'])
    df_list_g = df_list_g[df_list_g['종목명'] != '종목명']
    df_gain_raw = df_list_g.head(10).copy()
    df_gain_raw['거래대금'] = pd.to_numeric(df_gain_raw['거래대금'], errors='coerce')
    df_gain_raw['거래대금(억)'] = (df_gain_raw['거래대금'] / 100).round(1)
    df_gain_final = df_gain_raw[['종목명', '등락률', '거래대금(억)']].copy()
    df_gain_final.insert(0, '순위', range(1, len(df_gain_final) + 1))
    
    # C. 주요 뉴스
    url_news = "https://finance.naver.com/news/mainnews.naver"
    res_news = requests.get(url_news, headers=headers, timeout=10)
    soup_news = BeautifulSoup(res_news.text, 'html.parser')
    news_titles = soup_news.select('.mainNewsList .articleSubject a')
    news_list = [title.get_text().strip() for title in news_titles[:6]]
    
    return df_value_final, df_gain_final, news_list

def format_change_rate(val):
    val_str = str(val).strip().replace('%', '').replace('+', '')
    try:
        val_num = float(val_str)
        if val_num > 0: return f"<span class='up-color'>▲ +{val_num}%</span>"
        elif val_num < 0: return f"<span class='down-color'>▼ {val_num}%</span>"
        else: return f"<span class='flat-color'>0.00%</span>"
    except: return f"<span class='flat-color'>{val}</span>"

# 4. UI 렌더링
display_time, is_market_open = get_current_market_time()
st.title("📈 Live! 주식 단타 주도주 대시보드")
st.caption(f"📅 데이터 기준일: {datetime.now().strftime('%Y-%m-%d')} | 🔄 실시간 연동 완료")
st.success(f"📌 **현재 데이터 동기화 시점:** {display_time}")

try:
    df_value, df_gain, news = fetch_real_market_data()
    df_value['등락률'] = df_value['등락률'].apply(format_change_rate)
    df_gain['등락률'] = df_gain['등락률'].apply(format_change_rate)
    
    col1, col2, col3 = st.columns([1.3, 1.3, 1.4])
    with col1:
        st.subheader("💵 당일 거래대금 상위 (코스피)")
        st.write(df_value.set_index("순위").to_html(escape=False, unsafe_allow_html=True), unsafe_allow_html=True)
    with col2:
        st.subheader("🔥 당일 등락률 상위 (급등주)")
        st.write(df_gain.set_index("순위").to_html(escape=False, unsafe_allow_html=True), unsafe_allow_html=True)
    with col3:
        st.subheader("📰 실시간 주요 증시 뉴스")
        st.markdown("<br>", unsafe_allow_html=True)
        for idx, item in enumerate(news):
            st.markdown(f"**{idx+1}.** {item}")
            st.markdown("<hr style='margin:10px 0; border-top:1px dashed #ddd;'>", unsafe_allow_html=True)
except Exception as e:
    st.error(f"데이터 연동 중 오류 발생: {e}")

if is_market_open:
    time.sleep(60)
    st.rerun()
else:
    st.warning("⚠️ 주식시장이 마감되었습니다. 현재 데이터는 장 마감 시점(15:30)의 최종 데이터입니다.")