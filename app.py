import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import plotly.graph_objects as px
import plotly.express as px_lib
from plotly.subplots import make_subplots
import os

# 페이지 설정
st.set_page_config(
    page_title="청년층 부채 및 순자산 분석 대시보드",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 제목 및 스타일링
st.title("📊 청년층 부채 및 순자산 분석 대시보드 (SQLite 기반)")
st.markdown("""
본 대시보드는 **2018년, 2021년, 2023년 가구마스터 데이터**와 **신용거래융자 잔고 데이터**를 활용하여,
청년층 가구주(만 20세 ~ 39세)의 금융 부채 증가, 순자산 변화율, 그리고 소득 분위별 자산 격차 현황을 실시간 분석합니다.
""")

# 인코딩 자동 감지 함수
def load_csv_with_encodings(file):
    encodings = ["utf-8-sig", "cp949", "euc-kr"]
    for enc in encodings:
        try:
            # streamlit file uploader는 BytesIO나 StringIO 객체이므로 시크를 초기화하여 여러 번 읽을 수 있게 함
            file.seek(0)
            df = pd.read_csv(file, encoding=enc)
            return df, enc
        except Exception:
            continue
    return None, None

# 가중 중앙값 계산 유틸리티
def weighted_median(df, val_col, weight_col):
    if df.empty:
        return 0.0
    df_sorted = df.sort_values(by=val_col).copy()
    cumsum = df_sorted[weight_col].cumsum()
    cutoff = df_sorted[weight_col].sum() / 2.0
    median_row = df_sorted[cumsum >= cutoff].iloc[0]
    return float(median_row[val_col])

# 사이드바 설정
st.sidebar.header("📁 데이터 업로드 및 옵션")

# 컬럼명 디버깅 기능 사이드바 추가
show_columns = st.sidebar.checkbox("컬럼명 확인", value=False)

st.sidebar.subheader("1. 가구마스터 CSV 업로드")
uploaded_2018 = st.sidebar.file_uploader("2018 가구마스터 CSV", type=["csv"])
uploaded_2021 = st.sidebar.file_uploader("2021 가구마스터 CSV", type=["csv"])
uploaded_2023 = st.sidebar.file_uploader("2023 가구마스터 CSV", type=["csv"])

st.sidebar.subheader("2. 신용거래융자 XLSX 업로드")
uploaded_xlsx = st.sidebar.file_uploader("신용거래융자 잔고 XLSX (금융투자협회)", type=["xlsx"])

# 샘플 데이터 생성기 (업로드하지 않았을 때 데모용)
def create_sample_household_data(year):
    np.random.seed(year)
    n = 200
    ages = np.random.randint(18, 75, n)
    weight = np.random.uniform(500, 2000, n)
    
    # 청년층(20-39)에 대해 연도별 트렌드가 반영된 자산 분배 생성
    # 2018 -> 2023으로 갈수록 금융부채 증가, 자산평균 증가, 중앙값은 주택담보대출 증가 등으로 양극화되어 정체/감소
    if year == 2018:
        base_asset = np.random.exponential(25000, n) + 5000
        base_debt = np.random.exponential(6000, n) + 1000
        income_qt = np.random.randint(1, 6, n)
    elif year == 2021:
        base_asset = np.random.exponential(35000, n) + 12000
        base_debt = np.random.exponential(11000, n) + 2000
        income_qt = np.random.randint(1, 6, n)
    else: # 2023
        # 자산은 소수 부자 가구가 극단적으로 높아 평균은 상승하나 일하는 일반 청년은 정체
        base_asset = np.random.exponential(33000, n) + 8000
        # 금융부채는 영끌/금리인상으로 대폭 증가
        base_debt = np.random.exponential(13000, n) + 3000
        income_qt = np.random.randint(1, 6, n)

    # 분위수 조정을 위해 분위별 자산 보조 처리
    for i in range(n):
        # 5분위는 자산 2.5배 확대, 1분위는 부채 대폭 증가
        if income_qt[i] == 5:
            base_asset[i] *= 2.2
        elif income_qt[i] == 1:
            base_asset[i] *= 0.5
            base_debt[i] *= 1.4

    net_asset = base_asset - base_debt
    fin_asset = base_asset * np.random.uniform(0.2, 0.4, n)
    real_asset = base_asset - fin_asset
    fin_debt = base_debt * np.random.uniform(0.7, 0.95, n)

    df = pd.DataFrame({
        "조사연도": [year] * n,
        "가중값": weight,
        "가구주_만연령": ages,
        "순자산": net_asset,
        "부채": base_debt,
        "부채_금융부채": fin_debt,
        "자산_금융자산": fin_asset,
        "자산_실물자산": real_asset,
        "소득5분위코드": income_qt
    })
    return df

# 데이터 로드 로직
data_loaded = True
dfs = {}

# 필수 컬럼 정의
required_cols = [
    "조사연도", "가중값", "가구주_만연령", "순자산", "부채",
    "부채_금융부채", "자산_금융자산", "자산_실물자산", "소득5분위코드"
]

mapping_candidates = [
    "소득5분위코드", "보완_소득5분위코드", "소득5분위코드(보완)",
    "소득5분위코드_보완", "소득분위", "소득5분위"
]

# 데이터 체크 및 로드
file_dict = {
    2018: uploaded_2018,
    2021: uploaded_2021,
    2023: uploaded_2023
}

all_uploaded = all(v is not None for v in file_dict.values())

if not all_uploaded:
    st.info("💡 2018, 2021, 2023년 세 개의 가구마스터 CSV 파일을 모두 업로드하시면 실제 데이터를 분석합니다. 현재는 분석 시연용 데모 데이터로 구동 중입니다.")
    # 데모 데이터 생성
    for y in [2018, 2021, 2023]:
        dfs[y] = create_sample_household_data(y)
else:
    for y, file in file_dict.items():
        df, encoding = load_csv_with_encodings(file)
        if df is None:
            st.error(f"❌ {y} 가구마스터 파일을 읽을 수 없습니다. 인코딩 형식을 확인해 주세요.")
            st.stop()
            
        # 1. 컬럼명 자동 정리
        df.columns = (
            df.columns.astype(str)
            .str.strip()
            .str.replace("\n", "", regex=False)
            .str.replace(" ", "", regex=False)
        )
        
        # 2. 소득분위코드 자동 매핑
        mapped_col = None
        for cand in mapping_candidates:
            if cand in df.columns:
                mapped_col = cand
                break
        
        if mapped_col:
            df["소득5분위코드"] = df[mapped_col]
        
        # '조사연도' 생성
        if "조사연도" not in df.columns:
            df["조사연도"] = y
            
        # 디버깅 정보 수집용 원본 컬럼명 저장
        dfs[y] = df

# 필수 컬럼 검증
missing_warning_triggered = False
debug_original_columns = {}
debug_processed_columns = {}

for y, df in dfs.items():
    debug_original_columns[y] = list(df.columns)
    
    # 필수 컬럼 점검
    missing_cols = [c for c in required_cols if c not in df.columns]
    
    # 필수 컬럼 부재 시 중단
    if missing_cols:
        st.error(f"❌ {y}년 데이터에서 필수 컬럼이 검출되지 않았습니다.")
        st.write(f"- **현재 파일 컬럼명:** {list(df.columns)}")
        st.write(f"- **누락된 컬럼:** {missing_cols}")
        st.stop()
        
    debug_processed_columns[y] = list(df.columns)

# 컬럼 디버그 출력
if show_columns:
    st.markdown("### 🔍 컬럼명 디버깅 정보")
    cols_col1, cols_col2 = st.columns(2)
    with cols_col1:
        st.write("**[원본 파일 검출 컬럼명]**")
        for y, cols in debug_original_columns.items():
            st.write(f"- {y}년: {cols}")
    with cols_col2:
        st.write("**[분석 정규화 반영 컬럼명]**")
        for y, cols in debug_processed_columns.items():
            st.write(f"- {y}년: {cols}")

# SQLite 데이터베이스 생성 및 청년층 필터링 후 적재
conn = sqlite3.connect(":memory:")
cursor = conn.cursor()

# 하나의 큰 데이터프레임으로 변환
full_df = pd.concat([dfs[2018][required_cols], dfs[2021][required_cols], dfs[2023][required_cols]], ignore_index=True)

# 청년층 필터링 (가구주_만연령 20세 이상 39세 이하)
youth_df = full_df[(full_df["가구주_만연령"] >= 20) & (full_df["가구주_만연령"] <= 39)]

# SQL에 적재
youth_df.to_sql("household", conn, if_exists="replace", index=False)


# ==========================================
# 📊 [그래프 1] 청년층 금융부채와 순자산 평균/중앙값 변화
# ==========================================
st.subheader("📈 1. 청년층 금융부채와 순자산 평균·중앙값 변화")

# SQL 집계 (가중평균)
query_1 = """
SELECT 
    조사연도,
    SUM(부채_금융부채 * 가중값) / SUM(가중값) AS 금융부채_가중평균,
    SUM(순자산 * 가중값) / SUM(가중값) AS 순자산_가중평균
FROM 
    household
GROUP BY 
    조사연도
ORDER BY 
    조사연도 ASC
"""
summary_df = pd.read_sql_query(query_1, conn)

# 가중 중앙값은 SQL로 로우 데이터 가져와 계산
medians = []
for yr in [2018, 2021, 2023]:
    yr_data = youth_df[youth_df["조사연도"] == yr]
    med_val = weighted_median(yr_data, "순자산", "가중값")
    medians.append({"조사연도": yr, "순자산_중앙값": med_val})

medians_df = pd.DataFrame(medians)
chart1_df = pd.merge(summary_df, medians_df, on="조사연도")

# 차트 그리그 (Plotly 이중 축)
fig1 = make_subplots(specs=[[{"secondary_y": True}]])

# 금융부채 가중평균 (왼쪽 Y축)
fig1.add_trace(
    st.session_state.get("dummy", None) or 
    px.line(chart1_df, x="조사연도", y="금융부채_가중평균").data[0],
    secondary_y=False
)
fig1.data[-1].name = "금융부채 가중평균 (좌, 만원)"
fig1.data[-1].line.color = "#E53E3E"
fig1.data[-1].line.width = 3

# 순자산 가중평균 (오른쪽 Y축)
fig1.add_trace(
    px.line(chart1_df, x="조사연도", y="순자산_가중평균").data[0],
    secondary_y=True
)
fig1.data[-1].name = "순자산 가중평균 (우, 만원)"
fig1.data[-1].line.color = "#3182CE"
fig1.data[-1].line.width = 3

# 순자산 가중중앙값 (오른쪽 Y축)
fig1.add_trace(
    px.line(chart1_df, x="조사연도", y="순자산_중앙값").data[0],
    secondary_y=True
)
fig1.data[-1].name = "순자산 가중중앙값 (우, 만원)"
fig1.data[-1].line.color = "#319795"
fig1.data[-1].line.width = 3
fig1.data[-1].line.dash = "dash"

# 레이아웃 세부조정
fig1.update_layout(
    title_text="연도별 금융부채 및 순자산의 변화 추이(이중 축)",
    xaxis=dict(tickvals=[2018, 2021, 2023], title="조사연도"),
    yaxis=dict(title="금융부채 가중평균 (만원)", titlefont=dict(color="#E53E3E"), tickfont=dict(color="#E53E3E")),
    yaxis2=dict(title="순자산 가중평균/중앙값 (만원)", titlefont=dict(color="#2B6CB0"), tickfont=dict(color="#2B6CB0")),
    legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.8)"),
    hovermode="x unified",
    margin=dict(l=40, r=40, t=50, b=40)
)

c1_chart, c1_metrics = st.columns([2.5, 1])

with c1_chart:
    st.plotly_chart(fig1, use_container_width=True)

with c1_metrics:
    st.markdown("#### 🔄 2018 → 2023 변화율")
    
    # 변화율 계산
    row_2018 = chart1_df[chart1_df["조사연도"] == 2018].iloc[0]
    row_2023 = chart1_df[chart1_df["조사연도"] == 2023].iloc[0]
    
    rate_debt = ((row_2023["금융부채_가중평균"] - row_2018["금융부채_가중평균"]) / row_2018["금융부채_가중평균"]) * 100
    rate_net_avg = ((row_2023["순자산_가중평균"] - row_2018["순자산_가중평균"]) / row_2018["순자산_가중평균"]) * 100
    rate_net_med = ((row_2023["순자산_중앙값"] - row_2018["순자산_중앙값"]) / row_2018["순자산_중앙값"]) * 100
    
    st.metric(label="금융부채 평균 변화율", value=f"{rate_debt:+.1f}%", help="청년층의 대출부채 증가 현상을 반영합니다.")
    st.metric(label="순자산 평균 변화율", value=f"{rate_net_avg:+.1f}%", help="부동산 실물자산 가격 변동 및 전체 자산 규모 성장.")
    st.metric(label="순자산 중앙값 변화율", value=f"{rate_net_med:+.1f}%", help="가운데 있는 청년 가구의 실질 자산 상태.")

st.info("**💡 그래프 1 분석 결과:** 평균 순자산은 지속적으로 크게 증가한 반면, 순자산의 중앙값은 그보다 상승세가 둔화되었거나 감소하면서 부채 중심의 자산 팽창 속에서 자산 양극화가 심화되고 있음을 보여줍니다.")


# ==========================================
# 📊 [그래프 2] 청년층 소득분위별 순자산·금융부채 변화
# ==========================================
st.subheader("👥 2. 청년층 소득분위별 순자산·금융부채 변화")

selected_target = st.selectbox("분석 대상 지표를 선택해 주세요", ["순자산", "금융부채"])

target_col = "순자산" if selected_target == "순자산" else "부채_금융부채"

# SQL로 소득분위별 가중평균 집계
query_2 = f"""
SELECT 
    조사연도,
    소득5분위코드,
    SUM({target_col} * 가중값) / SUM(가중값) AS 가중평균
FROM 
    household
GROUP BY 
    조사연도, 소득5분위코드
ORDER BY 
    조사연도 ASC, 소득5분위코드 ASC
"""
qt_df = pd.read_sql_query(query_2, conn)

# Plotly 라인차트 생성
fig2 = px_lib.line(
    qt_df, 
    x="조사연도", 
    y="가중평균", 
    color="소득5분위코드",
    markers=True,
    category_orders={"소득5분위코드": [1, 2, 3, 4, 5]},
    labels={"가중평균": f"{selected_target} 가중평균 (만원)", "소득5분위코드": "소득 분위 (1~5분위)"},
    title=f"소득분위별 청년층 {selected_target} 추이 변화"
)
fig2.update_layout(
    xaxis=dict(tickvals=[2018, 2021, 2023]),
    hovermode="x unified",
    margin=dict(l=40, r=40, t=50, b=40)
)

c2_chart, c2_table = st.columns([2.5, 1])

with c2_chart:
    st.plotly_chart(fig2, use_container_width=True)

# 분위별 2018 -> 2023 변화율 테이블 연산
wt_rates = []
for qi in range(1, 6):
    # 순자산 분석
    idx_net_18 = youth_df[(youth_df["조사연도"] == 2018) & (youth_df["소득5분위코드"] == qi)]
    idx_net_23 = youth_df[(youth_df["조사연도"] == 2023) & (youth_df["소득5분위코드"] == qi)]
    
    net_avg_18 = (idx_net_18["순자산"] * idx_net_18["가중값"]).sum() / idx_net_18["가중값"].sum() if not idx_net_18.empty else 1.0
    net_avg_23 = (idx_net_23["순자산"] * idx_net_23["가중값"]).sum() / idx_net_23["가중값"].sum() if not idx_net_23.empty else 1.0
    
    # 금융부채 분석
    debt_avg_18 = (idx_net_18["부채_금융부채"] * idx_net_18["가중값"]).sum() / idx_net_18["가중값"].sum() if not idx_net_18.empty else 1.0
    debt_avg_23 = (idx_net_23["부채_금융부채"] * idx_net_23["가중값"]).sum() / idx_net_23["가중값"].sum() if not idx_net_23.empty else 1.0
    
    rate_net = ((net_avg_23 - net_avg_18) / net_avg_18) * 100
    rate_debt = ((debt_avg_23 - debt_avg_18) / debt_avg_18) * 100
    
    wt_rates.append({
        "소득분위": f"{qi}분위",
        "순자산 변화율": f"{rate_net:+.1f}%",
        "금융부채 변화율": f"{rate_debt:+.1f}%"
    })

rates_df = pd.DataFrame(wt_rates)

with c2_table:
    st.markdown("#### 📊 분위별 2018 → 2023 변화율 표")
    st.dataframe(rates_df, hide_index=True)

st.info("**💡 그래프 2 분석 결과:** 고소득층(4, 5분위)일수록 금융투자 및 실물자산 투자로 순자산 증가폭이 거대하지만, 저소득층(1분위)은 신용대출 등 금융부채 증가는 높으나 순자산 성장은 미약해 소득 분위수별 양극망 구축이 선명하게 목격됩니다.")


# ==========================================
# 📊 [그래프 3] 청년층 금융자산·실물자산 비중 변화
# ==========================================
st.subheader("🏢 3. 청년층 금융자산·실물자산 비중 변화")

# SQL로 금융자산 및 실물자산의 연도별 가가 평균 비중 집계
query_3 = """
SELECT 
    조사연도,
    SUM(자산_금융자산 * 가중값) AS 금융자산_합,
    SUM(자산_실물자산 * 가중값) AS 실물자산_합
FROM 
    household
GROUP BY 
    조사연도
"""
asset_df = pd.read_sql_query(query_3, conn)
asset_df["총자산_합"] = asset_df["금융자산_합"] + asset_df["실물자산_합"]
asset_df["금융자산 비중"] = (asset_df["금융자산_합"] / asset_df["총자산_합"]) * 100
asset_df["실물자산 비중"] = (asset_df["실물자산_합"] / asset_df["총자산_합"]) * 100

# Plotly Stacked Bar Chart를 그리기 위해 데이터 멜팅
melted_asset = pd.melt(
    asset_df, 
    id_vars=["조사연도"], 
    value_vars=["금융자산 비중", "실물자산 비중"],
    var_name="자산종류", 
    value_name="비중"
)

fig3 = px_lib.bar(
    melted_asset, 
    x="조사연도", 
    y="비중", 
    color="자산종류",
    title="연도별 자산 포트폴리오 비중 변화 (100% 누적 막대)",
    labels={"비중": "비중 (%)", "조사연도": "조사연도"},
    color_discrete_map={"금융자산 비중": "#4FD1C5", "실물자산 비중": "#F6AD55"}
)
fig3.update_layout(
    xaxis=dict(tickvals=[2018, 2021, 2023]),
    yaxis=dict(ticksuffix="%"),
    margin=dict(l=40, r=40, t=50, b=40)
)

st.plotly_chart(fig3, use_container_width=True)

st.info("**💡 그래프 3 분석 결과:** 청년 가구는 대다수의 자산이 실물자산(부동산, 임차보증금 등)에 집중되어 있습니다. 부동산 폭등 주기에 실물자산 비중이 한때 급증했으나 금리인상 및 전세사기 사태 등으로 자산 유동화(금융자산 비중 확대)에 관심이 쏠리는 양상이 보입니다.")


# ==========================================
# 📈 [추가] 신용거래융자 잔고 변화 (기타 XLSX 연계)
# ==========================================
st.subheader("💳 4. 신용거래융자 잔고 추이 분석 (금융투자협회 데이터)")

if uploaded_xlsx is not None:
    try:
        xlsx_df = pd.read_excel(uploaded_xlsx)
        
        # 컬럼 정규화
        xlsx_df.columns = (
            xlsx_df.columns.astype(str)
            .str.strip()
            .str.replace("\n", "", regex=False)
            .str.replace(" ", "", regex=False)
        )
        
        # 날짜 컬럼과 잔고금액 매핑 유도
        date_col = [c for c in xlsx_df.columns if "일자" in c or "날짜" in c or "계약일" in c or "연도" in c or "date" in c.lower()]
        value_col = [c for c in xlsx_df.columns if "잔고" in c or "금액" in c or "융자" in c or "balance" in c.lower()]
        
        if date_col and value_col:
            d_col = date_col[0]
            v_col = value_col[0]
            
            # 분석용 정규화
            plot_xlsx = xlsx_df[[d_col, v_col]].dropna()
            plot_xlsx.columns = ["날짜", "융자잔고"]
            
            # 시각화
            fig_xlsx = px_lib.line(
                plot_xlsx, 
                x="날짜", 
                y="융자잔고", 
                title="일자별 신용거래융자 총 잔고 추이",
                color_discrete_sequence=["#805AD5"]
            )
            st.plotly_chart(fig_xlsx, use_container_width=True)
            st.success("✅ 금융투자협회 신용거래융자 데이터 로드를 완료하였습니다.")
        else:
            st.warning("⚠️ 신용거래융자 융자시트에 '일자'이거나 '잔고/금액'에 상응하는 컬럼이 부재하여 파일 로드는 성공했으나 가시화는 스킵되었습니다.")
            if show_columns:
                st.write("컬럼 목록:", list(xlsx_df.columns))
    except Exception as e:
        st.error(f"❌ 임포트 에러가 발생했습니다: {str(e)}")
else:
    # 데모 잔고 그래프 제공
    st.info("💡 신용거래융자 잔고 XLSX 파일이 업로드되지 않아 금융투자협회의 청년 영끌 레버리지 트렌드를 대변하는 가상 자산 잔고 추이를 표시합니다.")
    dates = pd.date_range(start="2018-01-01", end="2023-12-31", freq="M")
    # 2020 ~ 2021년 동학개미운동으로 급상승 후 2022년 금리 인상 후 급락 트렌드
    trend = 50000 + (np.sin(np.linspace(-1.5, 4.5, len(dates))) * 25000) + np.random.normal(0, 1500, len(dates))
    demo_xlsx = pd.DataFrame({"날짜": dates, "융자잔고": trend})
    
    fig_xlsx_demo = px_lib.line(
        demo_xlsx, 
        x="날짜", 
        y="융자잔고", 
        title="[데모] 연도별 신용거래융자 총 잔고 추이 (영끌 추세 분석)",
        color_discrete_sequence=["#805AD5"]
    )
    st.plotly_chart(fig_xlsx_demo, use_container_width=True)


# ==========================================
# 📊 종합 인사이트 및 결론
# ==========================================
st.subheader("💡 청년 부채 및 순자산 데이터 분석 핵심 인사이트")
st.markdown("""
1. **금융부채의 가파른 확대 (영끌 열풍의 잔재)**:
   - 2018년 대비 2023년까지 금융부채의 가중평균 가치가 대폭 증가하였습니다. 이는 부동산 가격 폭등기 당시의 주택담보대출뿐만 아니라, 주식 및 가상자산 등 '빚투/영끌' 현상의 레버리지가 광범위하게 청년 가구에 안착되었음을 나타냅니다.

2. **순자산 평균과 중앙값의 분리 (자산 피라미드 왜곡)**:
   - 전체 청년층의 **순자산 가중평균은 늘어난 반면, 중앙값은 상대적으로 억제되거나 하락**하였습니다. 이는 소수의 초고급 청년 자산가가 평균 금액을 끌어올렸을 뿐, 청년 대다수의 실질적인 중간값 계층은 늘어난 부채와 금리 인상 비용으로 인해 실질 자산 증식을 누리지 못했음을 검증합니다.

3. **소득분위별 양극화 지표 구축**:
   - 상위 소득 수준(4, 5분위) 청년층의 순자산 폭증세 대비 하위 소득(1, 2분위)층의 저성장세가 대조를 이룹니다. 특히 저소득 청년은 비선호 금융업권의 금리 부담과 생계형 부채 비율이 상승하면서 부채 변화율이 소득 증보다 우선하는 한계 양상을 나타내고 있어 자산 양극화 개입 지원책의 당위성이 요구됩니다.

4. **실물자산(부동산) 위주의 포트폴리오 한계**:
   - 청년 가구의 유동성이 대부분 실물 및 보증금 자산에 귀속되어 있어 금리 리스크에 매우 취약하며, 향후 주택 시장 수축 시 청년 신용 불량 및 전세 보증 채무 부도 리스크로 직결될 우려가 지속되고 있습니다.
""")
