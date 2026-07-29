"""
RS River Monitor -- painel de monitoramento das estacoes ANA (Rio Grande do Sul).

Cada estacao e comparada APENAS com o seu proprio historico:
  - status do valor diario vs percentis P90/P97/P99 da propria estacao
  - CEI (excesso acumulado) da temporada vs. temporadas passadas da estacao

Os dados sao atualizados 1x/dia por um workflow do GitHub Actions
(etl/fetch_telemetry.py -> etl/build_index.py). O app apenas le os
arquivos ja processados (data/status.json, data/baseline.json,
data/current/*.parquet).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import hydro

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

st.set_page_config(page_title="RS River Monitor", page_icon="🌊", layout="wide")


# --------------------------------------------------------------------------
# Carregamento (cache invalida quando o arquivo muda de tamanho/mtime)
# --------------------------------------------------------------------------
@st.cache_data
def load_status() -> dict:
    return json.loads((DATA / "status.json").read_text(encoding="utf-8"))


@st.cache_data
def load_baseline() -> dict:
    return json.loads((DATA / "baseline.json").read_text(encoding="utf-8"))


@st.cache_data
def load_current(code: str) -> pd.Series:
    p = DATA / "current" / f"{code}.parquet"
    if not p.exists():
        return pd.Series(dtype=float)
    s = pd.read_parquet(p)["value"]
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


TRANSPARENT = "rgba(0,0,0,0)"


def styled(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor=TRANSPARENT, plot_bgcolor=TRANSPARENT,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        font=dict(size=13),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(128,128,128,.15)")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(128,128,128,.15)")
    return fig


# --------------------------------------------------------------------------
# Dados
# --------------------------------------------------------------------------
status = load_status()
baseline = load_baseline()
df = pd.DataFrame(status["stations"])

# --------------------------------------------------------------------------
# Cabecalho
# --------------------------------------------------------------------------
st.title("🌊 RS River Monitor")
st.caption(
    "Monitoramento diario de estacoes fluviometricas da ANA no Rio Grande do Sul. "
    "Cada estacao e comparada **apenas com o seu proprio historico** — sem benchmark externo."
)

badge = "🟢 Temporada ativa" if status["in_season"] else "⚪ Entre temporadas"
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Temporada de risco", status["season_label"], badge)
c2.metric("Estacoes", status["n_stations"])
c3.metric("Dado fresco (≤2d)", status["n_fresh"])
counts = status["status_counts"]
c4.metric("Alerta (alto+extremo)", counts.get("alto", 0) + counts.get("extremo", 0))
c5.metric("Atualizado", status["updated_utc"].split(" ")[0],
          status["updated_utc"].split(" ", 1)[1])

st.divider()

# --------------------------------------------------------------------------
# Mapa
# --------------------------------------------------------------------------
st.subheader("Mapa de status")
mapdf = df.dropna(subset=["lat", "lon"]).copy()
mapdf["cor"] = mapdf["status"].map(hydro.STATUS_COLORS)
mapdf["status_label"] = mapdf["status"].map(hydro.STATUS_LABEL)

fig_map = go.Figure()
for stt in ["normal", "elevado", "alto", "extremo", "sem_dado"]:
    sub = mapdf[mapdf["status"] == stt]
    if sub.empty:
        continue
    fig_map.add_trace(go.Scattermap(
        lat=sub["lat"], lon=sub["lon"], mode="markers",
        marker=dict(size=13, color=hydro.STATUS_COLORS[stt]),
        name=hydro.STATUS_LABEL[stt],
        text=sub["name"] + " — " + sub["river"].fillna(""),
        customdata=sub[["last_value", "unit", "cei_pct_rank", "last_date"]].values,
        hovertemplate="<b>%{text}</b><br>Ultima leitura: %{customdata[0]} %{customdata[1]}"
                      "<br>CEI rank: %{customdata[2]}%<br>%{customdata[3]}<extra></extra>",
    ))
fig_map.update_layout(
    map=dict(style="open-street-map",
             center=dict(lat=-29.7, lon=-53.2), zoom=5.4),
    height=460, margin=dict(l=0, r=0, t=0, b=0),
    legend=dict(orientation="h", yanchor="top", y=0.99, x=0.01,
                bgcolor="rgba(255,255,255,.7)"),
)
st.plotly_chart(fig_map, width="stretch")

# --------------------------------------------------------------------------
# Detalhe por estacao
# --------------------------------------------------------------------------
st.subheader("Detalhe da estacao")
labels = {f"{r['name']} ({r['code']}) — {r['river']}": r["code"]
          for _, r in df.sort_values("name").iterrows()}
sel_label = st.selectbox("Estacao", list(labels.keys()))
code = labels[sel_label]
row = df[df["code"] == code].iloc[0]
info = baseline[code]
unit = info["unit"]

m1, m2, m3, m4 = st.columns(4)
lv = row["last_value"]
m1.metric("Ultima leitura", f"{lv:.1f} {unit}" if pd.notna(lv) else "—",
          hydro.STATUS_LABEL[row["status"]])
m2.metric("Data / frescor",
          row["last_date"] or "—",
          f"há {int(row['days_since'])}d" if pd.notna(row["days_since"]) else "sem dado")
m3.metric(f"CEI temporada {status['season_label']}", f"{row['cei_now']:.0f}",
          f"percentil {row['cei_pct_rank']:.0f}% vs {info['n_seasons']} temporadas")
m4.metric("Limiar P97 (propria estacao)", f"{info['threshold']:.1f} {unit}")

cur = load_current(code)
cur_season = hydro.season_slice(cur, status["season_year"])

gcol1, gcol2 = st.columns(2)

# --- Grafico 1: serie diaria da temporada vs percentis proprios -----------
with gcol1:
    st.markdown("**Serie diaria da temporada vs. percentis historicos**")
    fig = go.Figure()
    if not cur_season.empty:
        fig.add_trace(go.Scatter(
            x=cur_season.index, y=cur_season.values, mode="lines",
            name="Temporada atual", line=dict(color="#2E86AB", width=2)))
    for pname, color in [("p90", "#F6C453"), ("p97", "#E8871E"), ("p99", "#D7263D")]:
        fig.add_hline(y=info[pname], line=dict(color=color, dash="dash", width=1.3),
                      annotation_text=pname.upper(), annotation_position="right")
    fig.update_yaxes(title_text=f"Valor ({unit})")
    st.plotly_chart(styled(fig), width="stretch")

# --- Grafico 2: CEI acumulado vs envelope historico -----------------------
with gcol2:
    st.markdown("**CEI acumulado vs. envelope das temporadas passadas**")
    env = info["envelope"]
    days = list(range(hydro.SEASON_LEN_DAYS))
    fig2 = go.Figure()
    if env["max"]:
        fig2.add_trace(go.Scatter(x=days, y=env["max"], mode="lines",
                                  name="Maximo historico",
                                  line=dict(color="rgba(215,38,61,.4)", width=1)))
        fig2.add_trace(go.Scatter(x=days, y=env["p90"], mode="lines", name="P90",
                                  fill="tonexty", fillcolor="rgba(232,135,30,.12)",
                                  line=dict(color="rgba(232,135,30,.5)", width=1)))
        fig2.add_trace(go.Scatter(x=days, y=env["p50"], mode="lines",
                                  name="Mediana", fill="tonexty",
                                  fillcolor="rgba(46,134,171,.10)",
                                  line=dict(color="rgba(46,134,171,.6)", width=1)))
    if not cur_season.empty:
        curve = hydro.cei_curve(cur_season, info["threshold"])
        fig2.add_trace(go.Scatter(x=curve.index, y=curve.values, mode="lines",
                                  name="Temporada atual",
                                  line=dict(color="#111827", width=2.5)))
    fig2.update_xaxes(title_text="Dia da temporada (0 = 1-out)")
    fig2.update_yaxes(title_text="CEI acumulado")
    st.plotly_chart(styled(fig2), width="stretch")

# --------------------------------------------------------------------------
# Tabela geral
# --------------------------------------------------------------------------
st.subheader("Todas as estacoes")
tbl = df.copy()
tbl["status"] = tbl["status"].map(hydro.STATUS_LABEL)
tbl = tbl[["code", "name", "river", "municipality", "data_type", "unit",
           "last_date", "last_value", "days_since", "status",
           "cei_now", "cei_pct_rank", "n_seasons"]]
tbl.columns = ["Codigo", "Estacao", "Rio", "Municipio", "Tipo", "Un.",
               "Ult. data", "Ult. valor", "Dias atras", "Status",
               "CEI atual", "CEI rank %", "Temporadas"]
st.dataframe(tbl, width="stretch", hide_index=True,
             column_config={
                 "CEI rank %": st.column_config.ProgressColumn(
                     "CEI rank %", min_value=0, max_value=100, format="%.0f%%"),
             })

st.caption(
    "Fonte: ANA HidroWeb + telemetria SOAP (DadosHidrometeorologicos). "
    "CEI = Cumulative Excess Index (soma dos excessos diarios acima do P97 da "
    "propria estacao no periodo de risco 1-out a 30-jun). "
    "Projeto de portfolio — nao e recomendacao operacional."
)
