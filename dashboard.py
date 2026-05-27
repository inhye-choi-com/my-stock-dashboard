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

# [연동 완료] 제공해주신 구글 스프레드시트 공유 주소 및 쓰기용 웹앱 URL
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1pMpXBZh3sIDE79e7vNmUgdVEU8f-qbywYy7biuWoUNM/edit?usp=sharing"
GOOGLE_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbwKibxHE_3q73hiOOmBk1JL5895_rLb6eJNA0srE_-FA1QBFCGNvHchVY9E9Sg7DGH9/exec" # ⬅️ 본인의 웹앱 URL을 입력하세요!

# 상승/하락/추천 및 포트폴리오 감시 스타일 정의
st.markdown("""
<style>
    .up-color { color: #ef4444; font-weight: bold; }   
    .down-color { color: #3b82f6; font-weight: bold; } 
    .flat-color { color: #6b7280; }                   
    .recommend-row { background-color: #fef08a !important; font-weight: bold; }
    .portfolio-danger { background-color: #fee2e2 !important; color: #b91c1c !important; font-weight: bold; } 
    .portfolio-success { background-color: #dcfce7 !important; color: #15803d !important; font-weight: bold; } 
</style>
""", unsafe_allow_html=True)

# 시간 계산 로직
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

# 구글 스프레드시트에서 탭별로 읽어오는 함수 (gid 파라미터 추가)
def load_portfolio_from_sheets(url, sheet_name=None):
    try:
        if "/edit" in url:
            base_url = url.split("/edit")[0]
            if sheet_name:
                csv_url = f"{base_url}/gviz/tq?tqx=out:csv&sheet={sheet_name}"
            else:
                csv_url = base_url + "/export?format=csv"
        else:
            csv_url = url
        df = pd.read_csv(csv_url)
        return df
    except Exception as e:
        return pd.DataFrame()

# 네이버 증권 데이터 추출 함수
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
        if anchor: stocks.append({'종목명': anchor.get_text().strip(), '코드': anchor['href'].split('=')[-1]})
            
    df_v = pd.read_html(io.StringIO(str(table_v)))[0].dropna(subset=['종목명'])
    df_v = df_v[df_v['종목명'] != '종목명'].head(10).copy()
    actual_len_v = min(len(df_v), len(stocks))
    df_v = df_v.head(actual_len_v).copy()
    df_v['코드'] = [s['코드'] for s in stocks[:actual_len_v]]
    df_v['raw_val'] = pd.to_numeric(df_v['거래대금'], errors='coerce').fillna(0)
    df_v['거래대금(억)'] = (df_v['raw_val'] / 1000).round(1)
    
    url_g = f"https://finance.naver.com/sise/sise_rise.naver?sosok={sosok_code}"
    res_g = requests.get(url_g, headers=headers, timeout=10)
    soup_g = BeautifulSoup(res_g.text, 'html.parser')
    table_g = soup_g.find('table', {'class': 'type_2'})
    
    stocks_g = []
    rows_g = table_g.find_all('tr')
    for row in rows_g:
        anchor = row.find('a', {'class': 'tltle'})
        if anchor: stocks_g.append({'종목명': anchor.get_text().strip(), '코드': anchor['href'].split('=')[-1]})
            
    df_g = pd.read_html(io.StringIO(str(table_g)))[0].dropna(subset=['종목명'])
    df_g = df_g[df_g['종목명'] != '종목명'].head(10).copy()
    actual_len_g = min(len(df_g), len(stocks_g))
    df_g = df_g.head(actual_len_g).copy()
    df_g['코드'] = [s['코드'] for s in stocks_g[:actual_len_g]]
    df_g['raw_vol'] = pd.to_numeric(df_g['거래량'], errors='coerce').fillna(0)
    df_g['거래량(만)'] = (df_g['raw_vol'] / 10000).round(1)
    
    return df_v, df_g

def get_current_price(code, market_type):
    suffix = ".KS" if "코스피" in str(market_type) else ".KQ"
    try:
        ticker = yf.Ticker(f"{code}{suffix}")
        todays_data = ticker.history(period="1d")
        if not todays_data.empty: return int(todays_data['Close'].iloc[-1])
    except: pass
    return None

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
                mapping[anchor.get_text().strip()] = anchor['href'].split('=')[-1]
        except: pass
    return mapping

def get_stock_chart(code, name, period_choice, market_type):
    suffix = ".KS" if "코스피" in str(market_type) else ".KQ"
    full_code = f"{code}{suffix}"
    ticker = yf.Ticker(full_code)
    period_val, interval_val = ("1d", "1m") if period_choice == "하루 (1분봉)" else (("5d", "30m") if period_choice == "일주일 (30분봉)" else ("1mo", "1d"))
    df = ticker.history(period=period_val, interval=interval_val)
    if df.empty and period_choice == "하루 (1분봉)": df = ticker.history(period="5d", interval="30m")
    
    if not df.empty:
        df['MA5'] = df['Close'].rolling(window=5).mean()
        df['MA10'] = df['Close'].rolling(window=10).mean()
        df['MA20'] = df['Close'].rolling(window=20).mean()
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_width=[0.25, 0.75])
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="주가", increasing_line_color='#ef4444', decreasing_line_color='#3b82f6'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], line=dict(color='#ff9800', width=1.5), name='5일선'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA10'], line=dict(color='#4caf50', width=1.5), name='10일선'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], line=dict(color='#9c27b0', width=1.5), name='20일선'), row=1, col=1)
        colors = ['#ef4444' if row['Close'] >= row['Open'] else '#3b82f6' for _, row in df.iterrows()]
        fig.add_trace(go.Bar(x=df.index, y=df['Volume'], name="거래량", marker_color=colors), row=2, col=1)
        fig.update_layout(xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=10, b=10), height=400, template="plotly_white")
        st.plotly_chart(fig, use_container_width=True)

def parse_rate(val_str):
    try: return float(str(val_str).replace('%','').replace('+','').strip())
    except: return 0.0

# 4. UI 렌더링
display_time, is_market_open = get_current_market_time()
if is_market_open: st_autorefresh(interval=60000, key="datarefresh")

st.title("🔥 실시간 단타 매매 & 스마트 포트폴리오")
today_str = datetime.now().strftime('%Y-%m-%d')
st.caption(f"📅 기준일: {today_str} | 🔄 60초 간격 실시간 갱신 중")

# 데이터 미리 로드
sheet_df = load_portfolio_from_sheets(GOOGLE_SHEET_URL)
sell_df = load_portfolio_from_sheets(GOOGLE_SHEET_URL, sheet_name="매도현황")
code_master = get_all_stock_codes()

# ----------------- [새 기능] 매수 / 매도 관리 입력 폼 -----------------
st.markdown("---")
tab_buy, tab_sell = st.tabs(["➕ 새 주식 매수 추가", "➖ 주식 매도 기록"])

with tab_buy:
    with st.form("add_stock_form", clear_on_submit=True):
        f_col1, f_col2, f_col3, f_col4 = st.columns(4)
        with f_col1: new_name = st.text_input("종목명", placeholder="예: 삼성전자", key="b_name")
        with f_col2: new_price = st.number_input("매수가(원)", min_value=0, step=10, value=0, key="b_price")
        with f_col3: new_qty = st.number_input("보유주수(주)", min_value=1, step=1, value=1, key="b_qty")
        with f_col4: new_market = st.selectbox("시장", ["코스피", "코스닥"], key="b_market")
        submit_btn = st.form_submit_button("💼 포트폴리오에 매수 추가")
        
        if submit_btn:
            if new_name.strip() == "" or new_price <= 0: st.error("❌ 종목명과 정확한 매수 가격을 입력해 주세요.")
            elif GOOGLE_WEB_APP_URL == "여기에_복사한_웹앱_URL_입력": st.warning("⚠️ GOOGLE_WEB_APP_URL 설정을 완료해 주세요.")
            else:
                with st.spinner("구글 드라이브에 기록 중..."):
                    payload = {"action": "buy", "stock_name": new_name.strip(), "buy_price": int(new_price), "qty": int(new_qty), "market": new_market}
                    try:
                        requests.post(GOOGLE_WEB_APP_URL, json=payload)
                        st.success(f"🎉 {new_name} 매수 기록 완료!")
                        st.cache_data.clear()
                    except Exception as e: st.error(f"전송 실패: {e}")

with tab_sell:
    with st.form("sell_stock_form", clear_on_submit=True):
        s_col1, s_col2, s_col3 = st.columns(3)
        # 현재 보유중인 종목 리스트를 선택지로 제공
        active_stocks = sheet_df['종목명'].dropna().unique().tolist() if not sheet_df.empty else []
        with s_col1: sell_name = st.selectbox("매도할 종목 선택", active_stocks if active_stocks else ["보유 주식 없음"])
        with s_col2: sell_price = st.number_input("매도가(원)", min_value=0, step=10, value=0)
        with s_col3: sell_qty = st.number_input("매도 주수(주)", min_value=1, step=1, value=1)
        sell_btn = st.form_submit_button("🚨 실현 손익(매도) 확정")
        
        if sell_btn and sell_name != "보유 주식 없음":
            if sell_price <= 0: st.error("❌ 정확한 매도 가격을 입력해 주세요.")
            else:
                # 매수가(평단가) 찾아서 수익 자동 계산
                matching = sheet_df[sheet_df['종목명'] == sell_name]
                if not matching.empty:
                    buy_price_avg = pd.to_numeric(matching.iloc[0]['매수가'], errors='coerce')
                    profit_calculated = int((sell_price - buy_price_avg) * sell_qty)
                    
                    with st.spinner("매도 현황 탭에 기록 중..."):
                        payload = {
                            "action": "sell", "stock_name": sell_name, "sell_price": int(sell_price),
                            "qty": int(sell_qty), "profit": profit_calculated, "date": datetime.now().strftime("%Y-%m-%d %H:%M")
                        }
                        try:
                            requests.post(GOOGLE_WEB_APP_URL, json=payload)
                            st.success(f"🎉 {sell_name} {sell_qty}주 매도 완료! (수익: {profit_calculated:,}원)")
                            st.cache_data.clear()
                        except Exception as e: st.error(f"전송 실패: {e}")

# ----------------- 상단 실시간 보유 주식 종합 현황 -----------------
st.subheader("📋 내 실시간 보유 주식 종합 현황 (실시간 감시)")
my_stock_list = []

if not sheet_df.empty and "종목명" in sheet_df.columns:
    p_html = "<table style='width:100%; border-collapse:collapse; text-align:left;'>"
    p_html += "<tr style='border-bottom:2px solid #333; background-color:#f3f4f6; height:35px;'><th>종목명</th><th>매수가</th><th>보유주수</th><th>현재가</th><th>평가수익</th><th>수익률</th><th>매매 신호</th></tr>"
    
    for _, row in sheet_df.iterrows():
        name = str(row['종목명']).strip()
        buy_price = pd.to_numeric(row['매수가'], errors='coerce')
        qty = pd.to_numeric(row['보유주수'], errors='coerce') if '보유주수' in sheet_df.columns else 1
        if pd.isna(qty): qty = 1
        m_type = str(row['시장']).strip() if '시장' in sheet_df.columns else "코스피"
        
        if name in code_master and not pd.isna(buy_price):
            code = code_master[name]
            current_price = get_current_price(code, m_type)
            my_stock_list.append(name)
            
            if current_price:
                profit_rate = round(((current_price - buy_price) / buy_price) * 100, 2)
                total_profit = int((current_price - buy_price) * qty)
                row_style = "class='portfolio-danger'" if profit_rate <= -2.0 else ("class='portfolio-success'" if profit_rate >= 4.0 else "")
                signal = "🚨 [매도] -2% 이탈!" if profit_rate <= -2.0 else ("🎉 [익절] +4% 도달!" if profit_rate >= 4.0 else "➖ 보유 유지")
                
                rate_html = f"<span class='up-color'>+{profit_rate}%</span>" if profit_rate > 0 else (f"<span class='down-color'>{profit_rate}%</span>" if profit_rate < 0 else "<span>0.0%</span>")
                profit_html = f"<span class='up-color'>{total_profit:,}원</span>" if total_profit > 0 else (f"<span class='down-color'>{total_profit:,}원</span>" if total_profit < 0 else "<span>0원</span>")
                
                p_html += f"<tr {row_style} style='border-bottom:1px solid #ddd; height:40px;'><td><b>{name}</b></td><td>{int(buy_price):,}원</td><td>{int(qty):,}주</td><td>{current_price:,}원</td><td>{profit_html}</td><td>{rate_html}</td><td><b>{signal}</b></td></tr>"
    p_html += "</table>"
    st.markdown(p_html, unsafe_allow_html=True)
else:
    st.info("💡 구글 스프레드시트 구조를 확인해 주세요.")

# ----------------- 하단 시장 데이터 및 주도주 분석 -----------------
st.markdown("---")
market_tab = st.radio("📈 시장 선택", ["코스피 (KOSPI)", "코스닥 (KOSDAQ)"], horizontal=True)
sosok_code = 0 if market_tab == "코스피 (KOSPI)" else 1

try:
    df_v, df_g = fetch_market_data(sosok_code)
    recommendations = {}
    
    def build_custom_html_table(df, table_type):
        html = "<table style='width:100%; border-collapse:collapse;'>"
        html += "<tr style='border-bottom:2px solid #ddd; text-align:left;'><th>순위</th><th>종목명</th><th>등락률</th><th>" + ("거래대금(억)" if table_type=="value" else "거래량(만)") + "</th></tr>"
        for idx, row in df.iterrows():
            rate_num = parse_rate(row['등락률'])
            rate_html = f"<span class='up-color'>▲ +{rate_num}%</span>" if rate_num > 0 else (f"<span class='down-color'>▼ {rate_num}%</span>" if rate_num < 0 else "<span class='flat-color'>0.0%</span>")
            is_recommended = (table_type == "value" and float(row['거래대금(억)']) >= 500 and 3 <= rate_num <= 15) or (table_type == "volume" and int(row['raw_vol']) >= 1000000 and rate_num >= 7)
            if is_recommended:
                recommendations[row['종목명']] = f"💰 **[거래대금 주도주]** 수급 집중!" if table_type=="value" else f"🚀 **[거래량 폭발]** 저항대 돌파 중!"
            row_class = "class='recommend-row'" if is_recommended else ""
            html += f"<tr {row_class} style='border-bottom:1px solid #eee; height:35px;'><td>{idx+1}</td><td>{row['종목명']}</td><td>{rate_html}</td><td>{row['거래대금(억)' if table_type=='value' else '거래량(만)']}</td></tr>"
        return html + "</table>"

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
        st.subheader("🔍 주식 상세 분석 & 멀티 차트")
        select_options = ["-- 내 보유 주식 선택 --"] + my_stock_list + ["-- 시장 주도주 선택 --"] + stock_names if my_stock_list else stock_names
        st.selectbox("분석할 종목을 선택하세요", select_options, index=0, key="stock_selector_main")
        selected_stock_name = st.session_state.stock_selector_main
        if "--" in str(selected_stock_name): selected_stock_name = stock_names[0]
            
        if not sheet_df.empty and selected_stock_name in sheet_df['종목명'].values:
            stock_row = sheet_df[sheet_df['종목명'] == selected_stock_name].iloc[0]
            b_price, s_qty = pd.to_numeric(stock_row['매수가'], errors='coerce'), pd.to_numeric(stock_row['보유주수'], errors='coerce')
            c_price = get_current_price(code_master.get(selected_stock_name, "005930"), stock_row.get('시장', '코스피'))
            if c_price:
                p_rate = round(((c_price - b_price) / b_price) * 100, 2)
                p_val = int((c_price - b_price) * (1 if pd.isna(s_qty) else s_qty))
                st.info(f"📋 **{selected_stock_name}** 종목은 보유 중인 주식입니다.")
                m_col1, m_col2, m_col3 = st.columns(3)
                with m_col1: st.metric(label="보유 주수", value=f"{int(s_qty):,} 주")
                with m_col2: st.metric(label="매수가 ➡️ 현재가", value=f"{c_price:,}원", delta=f"{c_price - b_price:,}원")
                with m_col3: st.metric(label="수익률 (평가손익)", value=f"{p_rate}%", delta=f"{p_val:,}원", delta_color="normal" if p_rate>=4.0 else ("inverse" if p_rate<=-2.0 else "off"))
        
        period_choice = st.radio("차트 주기", ["하루 (1분봉)", "일주일 (30분봉)", "한달 (일봉)"], horizontal=True, key="chart_period_choice")
        selected_code = code_master.get(selected_stock_name, "005930")
        st.markdown(f"### 📊 {selected_stock_name} ({selected_code})")
        get_stock_chart(selected_code, selected_stock_name, period_choice, market_tab)

    # ----------------- [새 기능] 하단 확정 매도 실현 손익 현황판 -----------------
    st.markdown("---")
    st.subheader("💰 확정 실현 손익 (구글 문서 '매도현황' 탭 연동)")
    if not sell_df.empty and "수익금액" in sell_df.columns:
        sell_df['수익금액'] = pd.to_numeric(sell_df['수익금액'], errors='coerce').fillna(0)
        total_realized_profit = int(sell_df['수익금액'].sum())
        
        sc1, sc2 = st.columns([1, 3])
        with sc1:
            st.metric(label="누적 실현 손익 합계", value=f"{total_realized_profit:,}원", 
                      delta="우상향 중 🚀" if total_realized_profit > 0 else "주의 요망 📉",
                      delta_color="normal" if total_realized_profit >= 0 else "inverse")
        with sc2:
            st.dataframe(sell_df[['종목명', '매도가', '보유주수', '수익금액', '매도일자']], use_container_width=True)
    else:
        st.info("💡 아직 매도 확정된 내역이 없습니다. 주식을 매도하면 여기에 누적 손익이 표시됩니다.")

except Exception as e: st.error(f"데이터 연동 중 오류 발생: {e}")
