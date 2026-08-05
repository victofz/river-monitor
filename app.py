"""
RS River Monitor -- pagina publica de monitoramento das estacoes ANA (RS).

Cada estacao e comparada APENAS com o seu proprio historico. A temporada
e um ciclo continuo de 12 meses (1-jul a 30-jun) -- sem gap/entressafra:
jul-set e o inicio da propria temporada corrente.

Os dados sao atualizados por um workflow do GitHub Actions
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
        font-family: {SERIF}; font-size: 2.5rem; line-height: 1.15;
        color: {INK}; font-weight: 700; margin: 0 0 14px 0;
    }}
    .hero-lead {{
        font-size: 1.06rem; line-height: 1.65; color: {INK_SECOND};
        max-width: 720px; margin-bottom: 4px;
    }}
    .hero-lead b {{ color: {INK}; font-weight: 600; }}
    .hero-rule {{ border: none; border-top: 3px solid {INK}; margin: 20px 0 24px 0; }}

    /* ---- Metric tiles -- compactas, sem estourar/cortar texto ---- */
    [data-testid="stMetric"] {{
        background-color: {PANEL_BG}; border: 1px solid {BORDER};
        border-radius: 3px; padding: 10px 14px; min-width: 0;
    }}
    [data-testid="stMetricLabel"] {{
        color: {INK_MUTED}; font-size: .68rem; text-transform: uppercase;
        letter-spacing: .03em; white-space: normal; line-height: 1.3;
    }}
    [data-testid="stMetricValue"] {{
        color: {INK}; font-family: {SANS}; font-size: 1.22rem !important;
        line-height: 1.25; white-space: normal; word-break: break-word;
    }}
    [data-testid="stMetricDelta"] {{
        font-size: .74rem; white-space: normal; line-height: 1.3;
    }}

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
    .status-chip {{
        display: inline-block; padding: 3px 10px; border-radius: 3px;
        font-size: .78rem; font-weight: 600; color: {PANEL_BG};
    }}
    .foot {{ color: {INK_MUTED}; font-size: .8rem; line-height: 1.6; }}
    hr.thin {{ border: none; border-top: 1px solid {BORDER}; margin: 26px 0; }}
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


def pick_default_code(df: pd.DataFrame) -> str:
    """Estacao mais notavel agora, para abrir o detalhe ja com algo relevante."""
    for stt in ("extremo", "alto", "elevado"):
        sub = df[df["status"] == stt]
        if not sub.empty:
            return sub.iloc[0]["code"]
    return df.sort_values("name").iloc[0]["code"]


status = load_status()
baseline = load_baseline()
df = pd.DataFrame(status["stations"])
n_alert = status["status_counts"].get("alto", 0) + status["status_counts"].get("extremo", 0)

# ============================================================================
# HERO -- foco no dado, uma pincelada leve sobre o indice
# ============================================================================
st.markdown('<div class="hero-kicker">Dados públicos · ANA HidroWeb</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-title">O pulso dos rios do<br>Rio Grande do Sul</div>',
            unsafe_allow_html=True)
st.markdown("""
<p class="hero-lead">
Cinquenta estações fluviométricas da ANA, lidas todos os dias — <b>vazão e
nível</b>, rio a rio. Cada estação é comparada apenas ao seu próprio
histórico, que em algumas passa de oito décadas de registros, para mostrar
se a leitura de hoje está alta, baixa ou dentro do esperado para esta
época do ano.
</p>
""", unsafe_allow_html=True)
st.markdown('<hr class="hero-rule">', unsafe_allow_html=True)

# ============================================================================
# Retrato de hoje
# ============================================================================
c1, c2, c3, c4 = st.columns(4)
c1.metric("Estações monitoradas", status["n_stations"], delta_color="off")
c2.metric("Dado fresco (≤2 dias)", status["n_fresh"], f"de {status['n_stations']}", delta_color="off")
c3.metric("Estações em alerta", n_alert, "alto ou extremo", delta_color="off")
c4.metric("Última atualização", status["updated_utc"].split(" ")[0],
          status["updated_utc"].split(" ", 1)[1], delta_color="off")

st.write("")

# ============================================================================
# Explorar / Tabela
# ============================================================================
tab_explore, tab_table = st.tabs(["Explorar", "Tabela completa"])

# --------------------------------------------------------------------------
with tab_explore:
    if "selected_code" not in st.session_state:
        st.session_state.selected_code = pick_default_code(df)

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
            customdata=sub[["code", "last_value", "unit", "cei_pct_rank", "last_date"]].values,
            hovertemplate="<b>%{text}</b><br>Última leitura: %{customdata[1]} %{customdata[2]}"
                          "<br>CEI rank: %{customdata[3]}%<br>%{customdata[4]}<extra></extra>",
        ))
    fig_map.update_layout(
        map=dict(style="open-street-map", center=dict(lat=-29.7, lon=-53.2), zoom=5.3),
        height=460, margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor=PANEL_BG, font=dict(family=SANS, color=INK),
        legend=dict(orientation="h", yanchor="top", y=0.99, x=0.01,
                    bgcolor="rgba(255,255,255,.9)", bordercolor=BORDER, borderwidth=1),
    )

    map_col, detail_col = st.columns([1, 1.1])

    with map_col:
        st.caption("Clique num ponto do mapa para ver a série da estação →")
        event = st.plotly_chart(fig_map, width="stretch", on_select="rerun",
                                selection_mode="points", key="map_chart")
        pts = (event or {}).get("selection", {}).get("points", [])
        if pts:
            clicked_code = pts[0].get("customdata", [None])[0]
            if clicked_code:
                st.session_state.selected_code = clicked_code
        st.markdown(
            '<div class="note-box">Cor = status da leitura mais recente frente aos '
            'percentis <b>P90 / P97 / P99 da própria estação</b>.</div>',
            unsafe_allow_html=True)

    with detail_col:
        sorted_df = df.sort_values("name")
        options = sorted_df["code"].tolist()
        labels_map = dict(zip(sorted_df["code"],
                               sorted_df["name"] + " — " + sorted_df["river"].fillna("")))
        code = st.selectbox("Ou busque uma estação", options,
                            format_func=lambda c: labels_map.get(c, c),
                            key="selected_code")

        row = df[df["code"] == code].iloc[0]
        info = baseline[code]
        unit = info["unit"]
        idx_label = "Vazão" if info["data_type"] == "flow" else "Nível"

        chip_color = STATUS_COLORS[row["status"]]
        st.markdown(
            f'<h3 style="margin:2px 0 0">{row["name"]}</h3>'
            f'<p style="color:{INK_MUTED};font-size:.85rem;margin:2px 0 10px">'
            f'{row["river"] or "—"} · {row["municipality"] or "—"} '
            f'<span class="status-chip" style="background:{chip_color}">'
            f'{STATUS_LABEL[row["status"]]}</span></p>',
            unsafe_allow_html=True)

        lv = row["last_value"]
        m1, m2, m3 = st.columns(3)
        m1.metric(f"Última leitura ({idx_label.lower()})",
                  f"{lv:.1f} {unit}" if pd.notna(lv) else "—", delta_color="off")
        m2.metric("Atualizado", "hoje" if row["days_since"] == 0
                  else (f"há {int(row['days_since'])}d" if pd.notna(row["days_since"]) else "—"),
                  row["last_date"] or "sem dado", delta_color="off")
        m3.metric(f"CEI {status['season_label']}", f"{row['cei_now']:.0f}",
                  f"percentil {row['cei_pct_rank']:.0f}%" if pd.notna(row["cei_pct_rank"]) else "—",
                  delta_color="off")

    # ---- Grafico em destaque: vazao/nivel, temporada atual x faixa historica ----
    st.write("")
    st.markdown(f"**{idx_label} diária — temporada {status['season_label']} "
               f"vs. faixa histórica ({info['n_seasons']} temporadas)**")

    cur = load_current(code)
    season_start, _ = hydro.season_bounds(status["season_year"])
    cur_extended = cur[cur.index >= season_start]

    venv = info.get("value_envelope", {})
    fig = go.Figure()
    if venv.get("max"):
        env_dates = [season_start + pd.Timedelta(days=d) for d in range(hydro.SEASON_LEN_DAYS)]
        fig.add_trace(go.Scatter(x=env_dates, y=venv["max"], mode="lines",
                                 line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=env_dates, y=venv["min"], mode="lines",
                                 name="Faixa histórica (mín–máx)", line=dict(width=0),
                                 fill="tonexty", fillcolor="rgba(46,92,138,.13)",
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=env_dates, y=venv["p50"], mode="lines",
                                 name="Mediana histórica",
                                 line=dict(color=INK_MUTED, width=1, dash="dot")))
    for pname, color in [("p90", "#C99A56"), ("p97", "#C1652E"), ("p99", ACCENT)]:
        fig.add_hline(y=info[pname], line=dict(color=color, dash="dash", width=1), opacity=.6,
                      annotation_text=pname.upper(), annotation_font_size=9,
                      annotation_position="right")
    if not cur_extended.empty:
        fig.add_trace(go.Scatter(x=cur_extended.index, y=cur_extended.values, mode="lines",
                                 name=f"Temporada {status['season_label']}",
                                 line=dict(color=LINE_BLUE, width=2.6)))
        fig.add_trace(go.Scatter(x=[cur_extended.index[-1]], y=[cur_extended.values[-1]],
                                 mode="markers", marker=dict(color=LINE_BLUE, size=9,
                                 line=dict(color=PANEL_BG, width=1.5)), showlegend=False))
    fig.update_yaxes(title_text=f"{idx_label} ({unit})")
    st.plotly_chart(styled(fig, height=430), width="stretch")

    with st.expander("Ver detalhe do índice acumulado (CEI)"):
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
        cur_season = hydro.season_slice(cur, status["season_year"])
        if not cur_season.empty:
            curve = hydro.cei_curve(cur_season, info["threshold"])
            fig2.add_trace(go.Scatter(x=curve.index, y=curve.values, mode="lines",
                                      name="Temporada atual", line=dict(color=LINE_BLUE, width=2.2)))
        fig2.update_xaxes(title_text="Dia da temporada (0 = 1-jul)")
        fig2.update_yaxes(title_text="CEI acumulado")
        st.plotly_chart(styled(fig2, height=280), width="stretch")
        st.caption("CEI = soma dos excessos diários acima do limiar histórico P97 da "
                  "própria estação, acumulada ao longo da temporada.")

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
<b>Temporada:</b> ciclo contínuo de 12 meses, 1º de julho a 30 de junho —
sem intervalo entre temporadas.<br><br>
<b>CEI (Cumulative Excess Index):</b> soma dos excessos diários acima do
percentil P97 da própria estação, acumulada ao longo da temporada. Um CEI
alto significa uma temporada com excedentes mais frequentes ou intensos
que o normal <i>para aquele rio</i> — não é comparável entre estações de
tamanhos diferentes.<br><br>
<b>Faixa histórica (mín–máx):</b> para cada dia da temporada, a menor e a
maior leitura já registradas naquele dia específico, entre todas as
temporadas com cobertura suficiente da estação.<br><br>
<b>Fontes:</b> histórico diário via <a href="https://www.snirh.gov.br/hidroweb/">ANA HidroWeb</a>
e telemetria em tempo (quase) real via o serviço SOAP público
<code>DadosHidrometeorologicos</code> da ANA. Os dados são públicos e as
estações somam, em conjunto, mais de 3.000 estações-ano de histórico.<br><br>
<b>Atualização:</b> um job agendado (GitHub Actions) busca a telemetria
periodicamente, recalcula os índices e publica os resultados — sem
intervenção manual.
</div>
""", unsafe_allow_html=True)

st.markdown(
    '<p class="foot">Projeto de portfólio, dados públicos da ANA. '
    'Não é recomendação operacional, de segurança ou produto financeiro.</p>',
    unsafe_allow_html=True,
)
