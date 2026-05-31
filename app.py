import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

st.set_page_config(
    page_title="청년층 부채 및 순자산 분석 대시보드",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("📊 청년층 부채 및 순자산 분석 대시보드")
st.markdown("""
2018년, 2021년, 2023년 가구마스터 데이터를 활용하여  
청년층 가구주(만 20세~39세)의 금융부채, 순자산, 소득분위별 격차, 자산구성 변화를 분석합니다.
""")

def load_csv_with_encodings(file):
    encodings = ["utf-8-sig", "cp949", "euc-kr"]
    for enc in encodings:
        try:
            file.seek(0)
            return pd.read_csv(file, encoding=enc)
        except Exception:
            continue
    return None

def clean_columns(df):
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace("\n", "", regex=False)
        .str.replace(" ", "", regex=False)
    )
    return df

def weighted_median(df, value_col, weight_col):
    df = df[[value_col, weight_col]].dropna().sort_values(value_col)
    if df.empty or df[weight_col].sum() == 0:
        return np.nan

    cutoff = df[weight_col].sum() / 2
    cumsum = df[weight_col].cumsum()
    return df.loc[cumsum >= cutoff, value_col].iloc[0]

def safe_rate(new, old):
    if pd.isna(old) or old == 0:
        return np.nan
    return ((new - old) / old) * 100

st.sidebar.header("📁 데이터 업로드")
uploaded_2018 = st.sidebar.file_uploader("2018 가구마스터 CSV", type=["csv"])
uploaded_2021 = st.sidebar.file_uploader("2021 가구마스터 CSV", type=["csv"])
uploaded_2023 = st.sidebar.file_uploader("2023 가구마스터 CSV", type=["csv"])

required_cols = [
    "조사연도",
    "가중값",
    "가구주_만연령",
    "순자산",
    "부채",
    "부채_금융부채",
    "자산_금융자산",
    "자산_실물자산",
    "소득5분위코드"
]

income_candidates = [
    "소득5분위코드",
    "보완_소득5분위코드",
    "소득5분위코드(보완)",
    "소득5분위코드_보완",
    "소득분위",
    "소득5분위"
]

file_dict = {
    2018: uploaded_2018,
    2021: uploaded_2021,
    2023: uploaded_2023
}

if not all(file_dict.values()):
    st.info("2018, 2021, 2023년 CSV 파일을 모두 업로드해 주세요.")
    st.stop()

dfs = {}

for year, file in file_dict.items():
    df = load_csv_with_encodings(file)

    if df is None:
        st.error(f"{year}년 CSV 파일을 읽을 수 없습니다. 인코딩을 확인해 주세요.")
        st.stop()

    df = clean_columns(df)

    income_col = None
    for cand in income_candidates:
        if cand in df.columns:
            income_col = cand
            break

    if income_col is not None:
        df["소득5분위코드"] = df[income_col]

    if "조사연도" not in df.columns:
        df["조사연도"] = year

    missing_cols = [col for col in required_cols if col not in df.columns]

    if missing_cols:
        st.error(f"{year}년 데이터에서 필수 컬럼이 없습니다: {missing_cols}")
        st.write("현재 파일 컬럼명:", list(df.columns))
        st.stop()

    dfs[year] = df[required_cols].copy()

full_df = pd.concat(
    [dfs[2018], dfs[2021], dfs[2023]],
    ignore_index=True
)

# Q1~Q5 형태의 소득분위코드를 숫자 1~5로 변환
full_df["소득5분위코드"] = (
    full_df["소득5분위코드"]
    .astype(str)
    .str.extract(r"(\d+)")[0]
)

numeric_cols = [
    "조사연도",
    "가중값",
    "가구주_만연령",
    "순자산",
    "부채",
    "부채_금융부채",
    "자산_금융자산",
    "자산_실물자산",
    "소득5분위코드"
]

for col in numeric_cols:
    full_df[col] = pd.to_numeric(full_df[col], errors="coerce")

full_df = full_df.dropna(subset=[
    "조사연도",
    "가중값",
    "가구주_만연령",
    "순자산",
    "부채_금융부채",
    "자산_금융자산",
    "자산_실물자산",
    "소득5분위코드"
])

youth_df = full_df[
    (full_df["가구주_만연령"] >= 20) &
    (full_df["가구주_만연령"] <= 39)
].copy()

if youth_df.empty:
    st.error("청년층 조건에 해당하는 데이터가 없습니다.")
    st.stop()

conn = sqlite3.connect(":memory:")
youth_df.to_sql("household", conn, if_exists="replace", index=False)

st.subheader("📈 1. 청년층 금융부채와 순자산 평균·중앙값 변화")

query_1 = """
SELECT
    조사연도,
    SUM(부채_금융부채 * 가중값) / SUM(가중값) AS 금융부채_가중평균,
    SUM(순자산 * 가중값) / SUM(가중값) AS 순자산_가중평균
FROM household
GROUP BY 조사연도
ORDER BY 조사연도
"""

summary_df = pd.read_sql_query(query_1, conn)

median_rows = []
for year in sorted(youth_df["조사연도"].unique()):
    temp = youth_df[youth_df["조사연도"] == year]
    median_rows.append({
        "조사연도": year,
        "순자산_중앙값": weighted_median(temp, "순자산", "가중값")
    })

median_df = pd.DataFrame(median_rows)
chart1_df = pd.merge(summary_df, median_df, on="조사연도")

fig1 = make_subplots(specs=[[{"secondary_y": True}]])

fig1.add_trace(
    go.Scatter(
        x=chart1_df["조사연도"],
        y=chart1_df["금융부채_가중평균"],
        mode="lines+markers",
        name="금융부채 가중평균"
    ),
    secondary_y=False
)

fig1.add_trace(
    go.Scatter(
        x=chart1_df["조사연도"],
        y=chart1_df["순자산_가중평균"],
        mode="lines+markers",
        name="순자산 가중평균"
    ),
    secondary_y=True
)

fig1.add_trace(
    go.Scatter(
        x=chart1_df["조사연도"],
        y=chart1_df["순자산_중앙값"],
        mode="lines+markers",
        name="순자산 중앙값",
        line=dict(dash="dash")
    ),
    secondary_y=True
)

fig1.update_layout(
    title="청년층 금융부채와 순자산 평균·중앙값 변화",
    hovermode="x unified",
    legend=dict(x=0.01, y=0.99),
    margin=dict(l=40, r=40, t=60, b=40)
)

fig1.update_xaxes(
    title_text="조사연도",
    tickvals=sorted(chart1_df["조사연도"].unique())
)

fig1.update_yaxes(
    title_text="금융부채 가중평균",
    secondary_y=False
)

fig1.update_yaxes(
    title_text="순자산 평균·중앙값",
    secondary_y=True
)

col1, col2 = st.columns([2.5, 1])

with col1:
    st.plotly_chart(fig1, use_container_width=True)

with col2:
    st.markdown("#### 2018 → 2023 변화율")

    row_2018 = chart1_df[chart1_df["조사연도"] == 2018]
    row_2023 = chart1_df[chart1_df["조사연도"] == 2023]

    if not row_2018.empty and not row_2023.empty:
        r18 = row_2018.iloc[0]
        r23 = row_2023.iloc[0]

        debt_rate = safe_rate(
            r23["금융부채_가중평균"],
            r18["금융부채_가중평균"]
        )
        avg_rate = safe_rate(
            r23["순자산_가중평균"],
            r18["순자산_가중평균"]
        )
        med_rate = safe_rate(
            r23["순자산_중앙값"],
            r18["순자산_중앙값"]
        )

        st.metric("금융부채 평균", f"{debt_rate:+.1f}%")
        st.metric("순자산 평균", f"{avg_rate:+.1f}%")
        st.metric("순자산 중앙값", f"{med_rate:+.1f}%")
    else:
        st.warning("2018년 또는 2023년 데이터가 없어 변화율을 계산할 수 없습니다.")

st.info("평균과 중앙값의 차이를 함께 보면, 일부 고자산 청년층이 평균을 끌어올렸는지 확인할 수 있습니다.")

st.subheader("👥 2. 청년층 소득분위별 순자산·금융부채 변화")

selected_target = st.selectbox(
    "분석 대상 지표 선택",
    ["순자산", "금융부채"]
)

target_col = "순자산" if selected_target == "순자산" else "부채_금융부채"

query_2 = f"""
SELECT
    조사연도,
    소득5분위코드,
    SUM({target_col} * 가중값) / SUM(가중값) AS 가중평균
FROM household
GROUP BY 조사연도, 소득5분위코드
ORDER BY 조사연도, 소득5분위코드
"""

qt_df = pd.read_sql_query(query_2, conn)
qt_df["소득5분위코드"] = qt_df["소득5분위코드"].astype(int).astype(str) + "분위"

fig2 = px.line(
    qt_df,
    x="조사연도",
    y="가중평균",
    color="소득5분위코드",
    markers=True,
    title=f"소득분위별 청년층 {selected_target} 추이",
    labels={
        "조사연도": "조사연도",
        "가중평균": f"{selected_target} 가중평균",
        "소득5분위코드": "소득분위"
    }
)

fig2.update_layout(
    hovermode="x unified",
    margin=dict(l=40, r=40, t=60, b=40)
)

fig2.update_xaxes(
    tickvals=sorted(youth_df["조사연도"].unique())
)

col3, col4 = st.columns([2.5, 1])

with col3:
    st.plotly_chart(fig2, use_container_width=True)

change_rows = []

for q in sorted(youth_df["소득5분위코드"].dropna().unique()):
    d18 = youth_df[
        (youth_df["조사연도"] == 2018) &
        (youth_df["소득5분위코드"] == q)
    ]
    d23 = youth_df[
        (youth_df["조사연도"] == 2023) &
        (youth_df["소득5분위코드"] == q)
    ]

    if d18.empty or d23.empty:
        continue

    net18 = (d18["순자산"] * d18["가중값"]).sum() / d18["가중값"].sum()
    net23 = (d23["순자산"] * d23["가중값"]).sum() / d23["가중값"].sum()

    debt18 = (d18["부채_금융부채"] * d18["가중값"]).sum() / d18["가중값"].sum()
    debt23 = (d23["부채_금융부채"] * d23["가중값"]).sum() / d23["가중값"].sum()

    change_rows.append({
        "소득분위": f"{int(q)}분위",
        "순자산 변화율": f"{safe_rate(net23, net18):+.1f}%",
        "금융부채 변화율": f"{safe_rate(debt23, debt18):+.1f}%"
    })

change_df = pd.DataFrame(change_rows)

with col4:
    st.markdown("#### 분위별 2018 → 2023 변화율")
    st.dataframe(change_df, hide_index=True)

st.info("소득분위별 선의 기울기 차이를 통해 청년층 내부의 자산 격차 확대 여부를 확인할 수 있습니다.")

st.subheader("🏢 3. 청년층 금융자산·실물자산 비중 변화")

query_3 = """
SELECT
    조사연도,
    SUM(자산_금융자산 * 가중값) AS 금융자산_합,
    SUM(자산_실물자산 * 가중값) AS 실물자산_합
FROM household
GROUP BY 조사연도
ORDER BY 조사연도
"""

asset_df = pd.read_sql_query(query_3, conn)

asset_df["총자산_합"] = asset_df["금융자산_합"] + asset_df["실물자산_합"]
asset_df["금융자산 비중"] = asset_df["금융자산_합"] / asset_df["총자산_합"] * 100
asset_df["실물자산 비중"] = asset_df["실물자산_합"] / asset_df["총자산_합"] * 100

melted_asset = asset_df.melt(
    id_vars="조사연도",
    value_vars=["금융자산 비중", "실물자산 비중"],
    var_name="자산종류",
    value_name="비중"
)

fig3 = px.bar(
    melted_asset,
    x="조사연도",
    y="비중",
    color="자산종류",
    title="청년층 금융자산·실물자산 비중 변화",
    labels={
        "조사연도": "조사연도",
        "비중": "비중(%)",
        "자산종류": "자산종류"
    }
)

fig3.update_layout(
    barmode="stack",
    yaxis=dict(ticksuffix="%"),
    margin=dict(l=40, r=40, t=60, b=40)
)

fig3.update_xaxes(
    tickvals=sorted(asset_df["조사연도"].unique())
)

st.plotly_chart(fig3, use_container_width=True)

st.info("금융자산과 실물자산 비중 변화를 통해 청년층 자산구조가 부동산·보증금 중심인지, 금융자산 중심으로 이동했는지 확인할 수 있습니다.")

st.subheader("💡 종합 인사이트")
st.markdown("""
1. 금융부채 가중평균이 상승했다면 청년층의 레버리지 부담이 커졌다고 해석할 수 있습니다.
2. 순자산 평균은 상승했지만 중앙값이 하락하거나 정체했다면, 자산 증가가 일부 계층에 집중되었을 가능성이 있습니다.
3. 소득분위별 순자산 증가율 차이가 크다면 청년층 내부 자산격차가 확대된 것으로 볼 수 있습니다.
4. 실물자산 비중이 높다면 청년층 자산이 주거·부동산 관련 자산에 묶여 있을 가능성이 큽니다.
""")
