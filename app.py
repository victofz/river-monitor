"""
RS River Monitor -- pagina publica de monitoramento das estacoes ANA (RS).

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

# ============================================================================
# Paleta sobria -- vermelho reservado a alertas reais, nao a decoracao
# ============================================================================
PAGE_BG = "#F7F6F3"
PANEL_BG = "#FFFFFF"
BORDER = "#E3E1DB"
INK = "#14171A"
INK_SECOND = "#54524C"
INK_MUTED = "#8A8780"
ACCENT = "#B23A2E"          # vermelho apagado -- so para o essencial
LINE_BLUE = "#2E5C8A"        # serie "temporada atual"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
SERIF = "Georgia, 'Iowan Old Style', 'Times New Roman', serif"

# escala de severidade -- reservada, nunca reaproveitada para outra coisa
STATUS_COLORS = {
    "normal": "#9C9A93",
    "elevado": "#C99A56",
    "alto": "#C1652E",
    "extremo": ACCENT,
    "sem_dado": "#D4D2CB",
}
STATUS_LABEL = hydro.STATUS_LABEL

st.markdown(f"""
<style>
    .stApp {{ background-color: {PAGE_BG}; font-family: {SANS}; }}
    .block-container {{ padding-top: 2.2rem; max-width: 1180px; }}
    h1, h2, h3 {{ font-family: {SANS}; color: {INK}; }}

    /* ---- Hero ---- */
    .hero-kicker {{
        color: {ACCENT}; font-size: .78rem; font-weight: 700;
        letter-spacing: .12em; text-transform: uppercase; margin-bottom: 6px;
    }}
    .hero-title {{
        font-family: {SERIF}; font-size: 2.6rem; line-height: 1.15;
        color: {INK}; font-weight: 700; margin: 0 0 14px 0;
    }}
    .hero-lead {{
        font-size: 1.08rem; line-height: 1.65; color: {INK_SECOND};
        max-width: 760px; margin-bottom: 4px;
    }}
    .hero-rule {{ border: none; border-top: 3px solid {INK}; margin: 22px 0 26px 0; }}

    /* ---- Corpo editorial (como funciona) ---- */
    .lede {{
        font-size: 1.0rem; line-height: 1.7; color: {INK_SECOND};
        max-width: 760px;
    }}
    .step-num {{
        font-family: {SERIF}; font-size: 1.6rem; color: {ACCENT};
        font-weight: 700; line-height: 1;
    }}
    .step-title {{ font-weight: 700; color: {INK}; margin: 6px 0 4px 0; }}
    .step-body {{ color: {INK_SECOND}; font-size: .92rem; line-height: 1.55; }}

    /* ---- Metric tiles ---- */
    [data-testid="stMetric"] {{
        background-color: {PANEL_BG}; border: 1px solid {BORDER};
        border-radius: 3px; padding: 12px 16px;
    }}
    [data-testid="stMetricLabel"] {{
        color: {INK_MUTED}; font-size: .74rem; text-transform: uppercase;
        letter-spacing: .04em;
    }}
    [data-testid="stMetricValue"] {{ color: {INK}; font-family: {SANS}; }}

    /* ---- Tabs ---- */
    .stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid {BORDER}; }}
    .stTabs [data-baseweb="tab"] {{ color: {INK_SECOND}; font-weight: 600; }}
    .stTabs [aria-selected="true"] {{
        color: {INK} !important; border-bottom: 2px solid {ACCENT} !important;
    }}

    [data-testid="stDataFrame"] {{ border: 1px solid {BORDER}; }}

    .note-box {{
        background-color: {PANEL_BG}; border: 1px solid {BORDER}; border-radius: 3px;
        padding: 10px 14px; color: {INK_MUTED}; font-size: .84rem; line-height: 1.5;
    }}
    .foot {{ color: {INK_MUTED}; font-size: .8rem; line-height: 1.6; }}
    hr.thin {{ border: none; border-top: 1px solid {BORDER}; margin: 30px 0; }}
</style>
""", unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Carregamento
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


def styled(fig: go.Figure, height: int = 340) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=36, b=10),
        paper_bgcolor=PANEL_BG, plot_bgcolor=PANEL_BG,
        font=dict(size=12, color=INK, family=SANS),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(showgrid=True, gridcolor="#EEEDE8", linecolor=BORDER, tickcolor=BORDER)
    fig.update_yaxes(showgrid=True, gridcolor="#EEEDE8", linecolor=BORDER, tickcolor=BORDER)
    return fig


status = load_status()
baseline = load_baseline()
df = pd.DataFrame(status["stations"])
n_alert = status["status_counts"].get("alto", 0) + status["status_counts"].get("extremo", 0)

# ============================================================================
# HERO -- pagina de apresentacao para um leitor publico
# ============================================================================
st.markdown('<div class="hero-kicker">Dados públicos · ANA HidroWeb</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-title">O pulso dos rios do<br>Rio Grande do Sul</div>',
            unsafe_allow_html=True)
st.markdown(f"""
<p class="hero-lead">
Um painel público e atualizado diariamente que acompanha <b>50 estações
fluviométricas</b> da Agência Nacional de Águas (ANA) espalhadas pelo estado.
Em vez de comparar rios entre si, cada estação é medida <b>contra o seu
próprio histórico</b> — em alguns casos, quase um século de registros —
para responder a uma pergunta simples: <i>este nível de água é normal para
este rio, nesta época do ano?</i>
</p>
""", unsafe_allow_html=True)
st.markdown('<hr class="hero-rule">', unsafe_allow_html=True)

# ============================================================================
# Como funciona -- explicativo editorial
# ============================================================================
st.markdown('<p class="lede">'
    'O Rio Grande do Sul tem um dos registros hidrológicos mais longos do '
    'Brasil, com estações que medem vazão e nível diariamente desde as '
    'décadas de 1930-40. Este painel usa esse histórico para dar contexto '
    'a cada leitura atual — sem comparar bacias diferentes entre si, que '
    'têm escalas naturalmente distintas.</p>', unsafe_allow_html=True)

s1, s2, s3 = st.columns(3)
with s1:
    st.markdown('<div class="step-num">01</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-title">Leitura diária</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-body">A cada dia, o painel busca as leituras mais '
                'recentes de vazão ou nível direto da telemetria pública da ANA '
                '(atualização a cada ~15 minutos).</div>', unsafe_allow_html=True)
with s2:
    st.markdown('<div class="step-num">02</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-title">Contexto histórico</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-body">Cada valor é comparado aos percentis '
                'P90 / P97 / P99 <i>da própria estação</i> — o quanto ela '
                'historicamente ultrapassa esses patamares no período chuvoso '
                '(out–jun).</div>', unsafe_allow_html=True)
with s3:
    st.markdown('<div class="step-num">03</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-title">Índice acumulado (CEI)</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-body">Somando o excesso diário acima do limiar '
                'histórico ao longo da temporada, obtemos o CEI — e o comparamos '
                'ao CEI de todas as temporadas passadas daquela estação.</div>',
                unsafe_allow_html=True)

st.markdown('<hr class="thin">', unsafe_allow_html=True)

# ============================================================================
# Retrato atual
# ============================================================================
st.markdown("### Retrato de hoje")
badge = "temporada ativa" if status["in_season"] else "entre temporadas"
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Temporada de risco", status["season_label"], badge)
c2.metric("Estações monitoradas", status["n_stations"])
c3.metric("Dado fresco (≤2 dias)", status["n_fresh"])
c4.metric("Estações em alerta", n_alert, "alto ou extremo")
c5.metric("Última atualização", status["updated_utc"].split(" ")[0],
          status["updated_utc"].split(" ", 1)[1])

st.write("")

# ============================================================================
# Exploracao dos dados
# ============================================================================
tab_map, tab_station, tab_table = st.tabs(["Mapa", "Estação", "Dados"])

# --------------------------------------------------------------------------
with tab_map:
    mapdf = df.dropna(subset=["lat", "lon"]).copy()

    fig_map = go.Figure()
    for stt in ["normal", "elevado", "alto", "extremo", "sem_dado"]:
        sub = mapdf[mapdf["status"] == stt]
        if sub.empty:
            continue
        fig_map.add_trace(go.Scattermap(
            lat=sub["lat"], lon=sub["lon"], mode="markers",
            marker=dict(size=12, color=STATUS_COLORS[stt]),
            name=STATUS_LABEL[stt],
            text=sub["name"] + " — " + sub["river"].fillna(""),
            customdata=sub[["last_value", "unit", "cei_pct_rank", "last_date"]].values,
            hovertemplate="<b>%{text}</b><br>Última leitura: %{customdata[0]} %{customdata[1]}"
                          "<br>CEI rank: %{customdata[2]}%<br>%{customdata[3]}<extra></extra>",
        ))
    fig_map.update_layout(
        map=dict(style="open-street-map", center=dict(lat=-29.7, lon=-53.2), zoom=5.3),
        height=500, margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor=PANEL_BG, font=dict(family=SANS, color=INK),
        legend=dict(orientation="h", yanchor="top", y=0.99, x=0.01,
                    bgcolor="rgba(255,255,255,.9)", bordercolor=BORDER, borderwidth=1),
    )
    st.plotly_chart(fig_map, width="stretch")
    st.markdown(
        '<div class="note-box">A cor indica o status do último valor diário frente '
        'aos percentis <b>P90 / P97 / P99 da própria estação</b> — nunca comparado '
        'a outra estação. Passe o cursor sobre um ponto para ver o rank do CEI na '
        'temporada corrente.</div>', unsafe_allow_html=True)

# --------------------------------------------------------------------------
with tab_station:
    labels = {f"{r['name']} ({r['code']}) — {r['river']}": r["code"]
              for _, r in df.sort_values("name").iterrows()}
    sel_label = st.selectbox("Escolha uma estação", list(labels.keys()))
    code = labels[sel_label]
    row = df[df["code"] == code].iloc[0]
    info = baseline[code]
    unit = info["unit"]

    m1, m2, m3, m4 = st.columns(4)
    lv = row["last_value"]
    m1.metric("Última leitura", f"{lv:.1f} {unit}" if pd.notna(lv) else "—",
              STATUS_LABEL[row["status"]])
    m2.metric("Data / frescor", row["last_date"] or "—",
              f"há {int(row['days_since'])}d" if pd.notna(row["days_since"]) else "sem dado")
    m3.metric(f"CEI temporada {status['season_label']}", f"{row['cei_now']:.0f}",
              f"percentil {row['cei_pct_rank']:.0f}% de {info['n_seasons']} temporadas")
    m4.metric("Limiar P97 (própria estação)", f"{info['threshold']:.1f} {unit}")

    if not status["in_season"]:
        st.caption(
            "🟡 **Entressafra** — a temporada de risco (out–jun) está fechada; o CEI "
            "acima ficou congelado no valor final da última temporada. A leitura e o "
            "status já refletem o dado mais recente da estação, mesmo fora da janela."
        )

    st.write("")
    cur = load_current(code)
    season_start = hydro.season_bounds(status["season_year"])[0]
    cur_extended = cur[cur.index >= season_start]          # inclui a cauda de entressafra
    cur_season = hydro.season_slice(cur, status["season_year"])  # so out-jun, p/ o CEI
    gcol1, gcol2 = st.columns(2)

    with gcol1:
        st.markdown("**Série diária vs. percentis históricos** (temporada + entressafra)")
        fig = go.Figure()
        off_start, off_end = hydro.offseason_bounds(status["season_year"])
        off_end = min(off_end, pd.Timestamp.today().normalize())
        if off_end >= off_start:
            fig.add_vrect(x0=off_start, x1=off_end, fillcolor=INK_MUTED, opacity=.12,
                          line_width=0, annotation_text="entressafra",
                          annotation_position="top left",
                          annotation_font=dict(size=10, color=INK_MUTED))
        if not cur_extended.empty:
            fig.add_trace(go.Scatter(
                x=cur_extended.index, y=cur_extended.values, mode="lines",
                name="Leitura diária", line=dict(color=LINE_BLUE, width=2)))
        for pname, color in [("p90", "#C99A56"), ("p97", "#C1652E"), ("p99", ACCENT)]:
            fig.add_hline(y=info[pname], line=dict(color=color, dash="dash", width=1.2),
                          annotation_text=pname.upper(), annotation_position="right")
        fig.update_yaxes(title_text=f"Valor ({unit})")
        st.plotly_chart(styled(fig), width="stretch")

    with gcol2:
        st.markdown("**CEI acumulado vs. envelope das temporadas passadas**")
        env = info["envelope"]
        days = list(range(hydro.SEASON_LEN_DAYS))
        fig2 = go.Figure()
        if env["max"]:
            fig2.add_trace(go.Scatter(x=days, y=env["max"], mode="lines",
                                      name="Máximo histórico",
                                      line=dict(color="rgba(178,58,46,.30)", width=1)))
            fig2.add_trace(go.Scatter(x=days, y=env["p90"], mode="lines", name="P90",
                                      fill="tonexty", fillcolor="rgba(193,101,46,.08)",
                                      line=dict(color="rgba(193,101,46,.45)", width=1)))
            fig2.add_trace(go.Scatter(x=days, y=env["p50"], mode="lines", name="Mediana",
                                      fill="tonexty", fillcolor="rgba(140,138,128,.12)",
                                      line=dict(color="rgba(120,118,110,.55)", width=1)))
        if not cur_season.empty:
            curve = hydro.cei_curve(cur_season, info["threshold"])
            fig2.add_trace(go.Scatter(x=curve.index, y=curve.values, mode="lines",
                                      name="Temporada atual", line=dict(color=LINE_BLUE, width=2.2)))
        fig2.update_xaxes(title_text="Dia da temporada (0 = 1-out)")
        fig2.update_yaxes(title_text="CEI acumulado")
        st.plotly_chart(styled(fig2), width="stretch")

# --------------------------------------------------------------------------
with tab_table:
    tbl = df.copy()
    tbl["status"] = tbl["status"].map(STATUS_LABEL)
    tbl = tbl[["code", "name", "river", "municipality", "data_type", "unit",
               "last_date", "last_value", "days_since", "status",
               "cei_now", "cei_pct_rank", "n_seasons"]]
    tbl.columns = ["Código", "Estação", "Rio", "Município", "Tipo", "Un.",
                   "Últ. data", "Últ. valor", "Dias atrás", "Status",
                   "CEI atual", "CEI rank %", "Temporadas"]
    st.dataframe(tbl, width="stretch", hide_index=True, height=540,
                 column_config={
                     "CEI rank %": st.column_config.ProgressColumn(
                         "CEI rank %", min_value=0, max_value=100, format="%.0f%%"),
                 })

# ============================================================================
# Rodape / metodologia
# ============================================================================
st.markdown('<hr class="thin">', unsafe_allow_html=True)
with st.expander("Sobre a metodologia e as fontes"):
    st.markdown("""
<div class="foot">
<b>CEI (Cumulative Excess Index):</b> soma dos excessos diários acima do
percentil P97 da própria estação, calculado apenas dentro do período de
risco (1º de outubro a 30 de junho). Um CEI alto significa uma temporada
com excedentes mais frequentes ou intensos que o normal <i>para aquele
rio</i> — não é comparável entre estações de tamanhos diferentes.<br><br>
<b>Fontes:</b> histórico diário via <a href="https://www.snirh.gov.br/hidroweb/">ANA HidroWeb</a>
e telemetria em tempo (quase) real via o serviço SOAP público
<code>DadosHidrometeorologicos</code> da ANA. Os dados são públicos e as
estações somam, em conjunto, mais de 3.000 estações-ano de histórico.<br><br>
<b>Atualização:</b> um job agendado (GitHub Actions) busca a telemetria
diariamente, recalcula os índices e publica os resultados — sem
intervenção manual.
</div>
""", unsafe_allow_html=True)

st.markdown(
    '<p class="foot">Projeto de portfólio, dados públicos da ANA. '
    'Não é recomendação operacional, de segurança ou produto financeiro.</p>',
    unsafe_allow_html=True,
)
