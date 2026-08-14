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
# "normal" em verde (nao cinza) pra nao confundir com "sem_dado" no mapa
STATUS_COLORS = {
    "normal": "#5B8C6E",
    "elevado": "#C99A56",
    "alto": "#C1652E",
    "extremo": ACCENT,
    "sem_dado": "#C7C4BC",
}
STATUS_LABEL = hydro.STATUS_LABEL

# glifos ASCII: o conjunto de glifos do estilo OSM/MapLibre nao inclui
# setas unicode (a camada de texto some silenciosamente com ▲/▼)
TREND_SYMBOL = {"up": "^", "down": "v", "flat": "="}
TREND_LABEL = {"up": "subindo", "down": "descendo", "flat": "estável"}
TREND_COLOR = {"up": ACCENT, "down": LINE_BLUE, "flat": INK_MUTED}
TREND_HORIZON_DAYS = 3   # "proximos dias" -- primeiro horizonte de forecast >= isso

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
def load_current(code: str) -> pd.DataFrame:
    """Buffer rolante da estacao -- colunas 'flow' e/ou 'level'."""
    p = DATA / "current" / f"{code}.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


@st.cache_data
def load_forecast() -> dict:
    """Previsao operacional (ensemble ECMWF, ~15d) importada do RIVERFLOW --
    atualizada manualmente via etl/import_forecast.py, nao pelo job horario."""
    p = DATA / "forecast.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


@st.cache_data
def load_rain_forecast() -> dict:
    """Grade de chuva acumulada prevista (ensemble ECMWF) -- mesma origem e
    mesma cadencia de atualizacao manual do load_forecast() acima."""
    p = DATA / "rain_forecast.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


METRIC_LABEL = {"flow": "Vazão", "level": "Nível"}
EXCESS_LABEL = {"flow": "Excesso de vazão acumulado", "level": "Excesso de nível acumulado"}
FORECAST_COLOR = "#8A5C3B"


def season_month_ticks() -> tuple[list[int], list[str]]:
    """tickvals/ticktext (mm-dd) no dia 1 de cada mes da temporada (0 = 1-jul)."""
    anchor = pd.Timestamp("2000-07-01")  # ano bissexto -- cobre os 366 dias da temporada
    vals, text = [], []
    for day in range(hydro.SEASON_LEN_DAYS):
        d = anchor + pd.Timedelta(days=day)
        if d.day == 1:
            vals.append(day)
            text.append(d.strftime("%m-%d"))
    return vals, text


SEASON_TICKVALS, SEASON_TICKTEXT = season_month_ticks()


def pct_rank(value: float, distribution: list[float]) -> float:
    if not distribution:
        return float("nan")
    arr = pd.array(distribution, dtype=float)
    return float((arr <= value).mean() * 100.0)


def season_display(metric: str, season_choice: str, info: dict,
                    live_df: pd.DataFrame, cur_season_year: int):
    """Dados da curva 'destacada' no grafico -- temporada atual (buffer ao
    vivo) ou uma safra congelada (baseline.json) -- e metricas derivadas.

    Retorna dict com: days, values, label, is_current, last_value,
    last_date, days_since, cei_now, cei_pct_rank.
    """
    threshold = info["threshold"]
    if season_choice == "current":
        s = live_df[metric].dropna() if metric in live_df.columns else pd.Series(dtype=float)
        s = hydro.season_slice(s, cur_season_year)
        if s.empty:
            days, values = [], []
            last_value = last_date = days_since = None
        else:
            days = hydro.season_day(s.index, cur_season_year).tolist()
            values = s.values.tolist()
            last_date = s.index.max()
            last_value = float(s.iloc[-1])
            days_since = int((pd.Timestamp.today().normalize() - last_date.normalize()).days)
        curve = hydro.cei_curve(s, threshold) if not s.empty else pd.Series(dtype=float)
        cei_now = float(curve.iloc[-1]) if not curve.empty else 0.0
        label = "Temporada atual"
    else:
        sy = int(season_choice)
        arr = info.get("seasons", {}).get(season_choice, [])
        days = [i for i, v in enumerate(arr) if v is not None]
        values = [v for i, v in enumerate(arr) if v is not None]
        last_value = values[-1] if values else None
        last_date, days_since = None, None
        cei_series = hydro.cei_from_aligned(arr, threshold)
        cei_now = cei_series[-1] if cei_series else 0.0
        label = f"Temporada {sy}/{str(sy + 1)[-2:]}"

    return {
        "days": days, "values": values, "label": label,
        "is_current": season_choice == "current",
        "last_value": last_value, "last_date": last_date, "days_since": days_since,
        "cei_now": cei_now,
        "cei_pct_rank": pct_rank(cei_now, info.get("seasonal_totals", [])),
    }


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


def station_forecast(code: str, metric: str) -> dict | None:
    """Forecast da estacao PARA A METRICA pedida (o RIVERFLOW preve vazao e
    nivel separadamente), ou None se nao houver."""
    return forecast.get("stations", {}).get(code, {}).get("metrics", {}).get(metric)


def forecast_trend(code: str, metric: str, last_value) -> dict | None:
    """Tendencia prevista frente a leitura de hoje: dict com direction
    ('up'/'down'/'flat'), variacao % e o valor/prob previstos no primeiro
    horizonte >= TREND_HORIZON_DAYS. None se nao houver forecast/leitura."""
    fc = station_forecast(code, metric)
    if not fc or not last_value:
        return None
    pt = next((p for p in fc["points"] if p["horizon"] >= TREND_HORIZON_DAYS), None)
    if not pt:
        return None
    pct = (pt["q_median"] - last_value) / last_value * 100
    direction = "up" if pct > 5 else ("down" if pct < -5 else "flat")
    return {"direction": direction, "pct": pct, "horizon": pt["horizon"],
            "q_median": pt["q_median"], "trigger_prob_15d": fc["trigger_prob_15d"]}


status = load_status()
baseline = load_baseline()
forecast = load_forecast()
rain_forecast = load_rain_forecast()
df = pd.DataFrame(status["stations"])
# status.json e baseline.json sao escritos por jobs diferentes (bot horario
# vs. seed manual) e podem, por uma janela curta durante um redeploy, ficar
# fora de sincronia -- filtra aqui, na fronteira entre os dois, para nunca
# quebrar mais adiante (inclusive se baseline vier de um esquema antigo).
df = df[df["code"].map(lambda c: bool(baseline.get(c, {}).get("metrics")))].reset_index(drop=True)

if df.empty:
    st.error(
        "Não foi possível casar `data/status.json` com `data/baseline.json` "
        "(nenhuma estação em comum). Isso costuma ser um deploy que ficou "
        "com arquivos de commits diferentes em cache -- tente **Reboot app** "
        "no menu do Streamlit Cloud (não apenas recarregar a página)."
    )
    st.stop()

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
# Explorar / Previsão / Tabela
# ============================================================================
tab_explore, tab_forecast, tab_table = st.tabs(["Explorar", "Previsão", "Tabela completa"])

# --------------------------------------------------------------------------
with tab_explore:
    if "selected_code" not in st.session_state:
        st.session_state.selected_code = pick_default_code(df)
    if "selected_metric" not in st.session_state:
        st.session_state.selected_metric = None  # resolvido por estacao, abaixo
    if "selected_season" not in st.session_state:
        st.session_state.selected_season = "current"

    mapdf = df.dropna(subset=["lat", "lon"]).copy()

    # texto do hover montado aqui (em vez de no hovertemplate) -- cada linha
    # depende de dados que podem faltar (forecast, leitura), entao formatar
    # em Python evita "None"/"nan" aparecendo no rotulo
    def hover_fields(row) -> pd.Series:
        metric = row["data_type"]
        mlabel = METRIC_LABEL[metric]
        if row["last_value"] is None or pd.isna(row["last_value"]):
            reading = "Sem leitura recente"
        else:
            days = row["days_since"]
            quando = ("hoje" if days == 0 else
                      f"há {int(days)} dia{'s' if days != 1 else ''}")
            reading = (f"{mlabel} hoje: <b>{row['last_value']:.1f} {row['unit']}</b> "
                       f"({STATUS_LABEL[row['status']]}, {quando})")

        rank = ("Excesso acumulado na temporada: sem dado"
                if pd.isna(row["cei_pct_rank"]) else
                f"Excesso acumulado: acima de {row['cei_pct_rank']:.0f}% das temporadas")

        tr = forecast_trend(row["code"], metric, row["last_value"])
        if tr is None:
            trend_txt, risk_txt = "Previsão: não disponível", ""
            direction = None
        else:
            direction = tr["direction"]
            trend_txt = (f"Previsão {tr['horizon']}d: <b>{TREND_LABEL[direction]}</b> "
                         f"({tr['pct']:+.0f}%, {tr['q_median']:.1f} {row['unit']})")
            risk_txt = (f"Risco de passar do P95 em 15d: "
                        f"<b>{tr['trigger_prob_15d'] * 100:.0f}%</b>")
        return pd.Series({"hover_reading": reading, "hover_rank": rank,
                          "hover_trend": trend_txt, "hover_risk": risk_txt,
                          "trend_dir": direction})

    mapdf = pd.concat([mapdf, mapdf.apply(hover_fields, axis=1)], axis=1)

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
            customdata=sub[["code", "hover_reading", "hover_rank",
                             "hover_trend", "hover_risk"]].values,
            hovertemplate="<b>%{text}</b><br>%{customdata[1]}<br>%{customdata[2]}"
                          "<br>%{customdata[3]}<br>%{customdata[4]}<extra></extra>",
        ))

    # tendencia prevista (~3d) -- so nas estacoes com forecast, deslocada pro
    # norte pra nao cobrir a bolinha. Glifos ASCII e marcador invisivel de
    # ancora: o MapLibre nao desenha uma camada mode="text" pura, e nao tem
    # setas unicode no conjunto de glifos do estilo OSM
    for direction, sub in mapdf.dropna(subset=["trend_dir"]).groupby("trend_dir"):
        fig_map.add_trace(go.Scattermap(
            lat=sub["lat"] + 0.13, lon=sub["lon"], mode="markers+text",
            marker=dict(size=1, color="rgba(0,0,0,0)"),
            text=[TREND_SYMBOL[direction]] * len(sub),
            textposition="top center",
            textfont=dict(size=17, color=TREND_COLOR[direction]),
            hoverinfo="skip", showlegend=False,
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
            'percentis <b>P90 / P97 / P99 da própria estação</b>. Acima do ponto, '
            f'a tendência prevista para ~{TREND_HORIZON_DAYS} dias: '
            f'<b style="color:{TREND_COLOR["up"]}">^</b> subindo · '
            f'<b style="color:{TREND_COLOR["down"]}">v</b> descendo · '
            f'<b style="color:{TREND_COLOR["flat"]}">=</b> estável. '
            'Passe o mouse para ver leitura, tendência e risco.</div>',
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
        station = baseline[code]
        available_metrics = list(station["metrics"].keys())

        chip_color = STATUS_COLORS[row["status"]]
        st.markdown(
            f'<h3 style="margin:2px 0 0">{row["name"]}</h3>'
            f'<p style="color:{INK_MUTED};font-size:.85rem;margin:2px 0 10px">'
            f'{row["river"] or "—"} · {row["municipality"] or "—"} '
            f'<span class="status-chip" style="background:{chip_color}">'
            f'{STATUS_LABEL[row["status"]]}</span></p>',
            unsafe_allow_html=True)

        ctrl1, ctrl2 = st.columns([1, 1.3])
        with ctrl1:
            if len(available_metrics) > 1:
                metric = st.segmented_control(
                    "Métrica", available_metrics, default=station["primary_metric"],
                    format_func=lambda m: METRIC_LABEL[m], key=f"metric_{code}")
                metric = metric or station["primary_metric"]
            else:
                metric = available_metrics[0]
                st.caption(f"Métrica: **{METRIC_LABEL[metric]}** (única disponível)")
        info = station["metrics"][metric]

        with ctrl2:
            season_opts = ["current"] + sorted(info.get("seasons", {}).keys(), reverse=True)
            season_fmt = {"current": f"{status['season_label']} (atual)"}
            for sy_str in season_opts[1:]:
                sy = int(sy_str)
                season_fmt[sy_str] = f"{sy}/{str(sy + 1)[-2:]}"
            season_choice = st.selectbox(
                "Safra", season_opts, format_func=lambda s: season_fmt[s],
                key=f"season_{code}_{metric}")

        disp = season_display(metric, season_choice, info,
                              load_current(code), status["season_year"])

        m1, m2, m3 = st.columns(3)
        if disp["is_current"]:
            lv = disp["last_value"]
            m1.metric(f"Última leitura ({METRIC_LABEL[metric].lower()})",
                      f"{lv:.1f} {info['unit']}" if lv is not None else "—", delta_color="off")
            ds = disp["days_since"]
            m2.metric("Atualizado", "hoje" if ds == 0 else (f"há {ds}d" if ds is not None else "—"),
                      str(disp["last_date"].date()) if disp["last_date"] is not None else "sem dado",
                      delta_color="off")
            m3.metric(EXCESS_LABEL[metric], f"{disp['cei_now']:.0f}",
                      f"percentil {disp['cei_pct_rank']:.0f}%"
                      if pd.notna(disp["cei_pct_rank"]) else "—", delta_color="off")
        else:
            mx = max(disp["values"]) if disp["values"] else None
            m1.metric(f"Máximo na safra ({METRIC_LABEL[metric].lower()})",
                      f"{mx:.1f} {info['unit']}" if mx is not None else "—", delta_color="off")
            m2.metric(f"{EXCESS_LABEL[metric]} (final da safra)", f"{disp['cei_now']:.0f}",
                      delta_color="off")
            m3.metric("Percentil vs. histórico", f"{disp['cei_pct_rank']:.0f}%"
                      if pd.notna(disp["cei_pct_rank"]) else "—", delta_color="off")

    # ---- Grafico em destaque: vazao/nivel, safra escolhida x faixa historica ----
    st.write("")
    st.markdown(f"**{METRIC_LABEL[metric]} diária — {disp['label']} "
               f"vs. faixa histórica ({info['n_seasons']} temporadas)**")

    venv = info.get("value_envelope", {})
    fig = go.Figure()
    days_axis = list(range(hydro.SEASON_LEN_DAYS))
    if venv.get("max"):
        fig.add_trace(go.Scatter(x=days_axis, y=venv["max"], mode="lines",
                                 line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=days_axis, y=venv["min"], mode="lines",
                                 name="Faixa histórica (mín–máx)", line=dict(width=0),
                                 fill="tonexty", fillcolor="rgba(46,92,138,.13)",
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=days_axis, y=venv["p50"], mode="lines",
                                 name="Mediana histórica",
                                 line=dict(color=INK_MUTED, width=1, dash="dot")))
    for pname, color in [("p90", "#C99A56"), ("p97", "#C1652E"), ("p99", ACCENT)]:
        fig.add_hline(y=info[pname], line=dict(color=color, dash="dash", width=1), opacity=.6,
                      annotation_text=pname.upper(), annotation_font_size=9,
                      annotation_position="right")
    if disp["values"]:
        fig.add_trace(go.Scatter(x=disp["days"], y=disp["values"], mode="lines",
                                 name=disp["label"], line=dict(color=LINE_BLUE, width=2.6)))
        fig.add_trace(go.Scatter(x=[disp["days"][-1]], y=[disp["values"][-1]],
                                 mode="markers", marker=dict(color=LINE_BLUE, size=9,
                                 line=dict(color=PANEL_BG, width=1.5)), showlegend=False))

    # ---- Previsao (ensemble ECMWF, ~15d) -- so sobre a temporada ao vivo, e
    # so da metrica em tela (o RIVERFLOW preve vazao e nivel separadamente)
    fc = station_forecast(code, metric) if disp["is_current"] and disp["values"] else None
    if fc:
        fc_days = hydro.season_day(pd.to_datetime([p["date"] for p in fc["points"]]),
                                   status["season_year"]).tolist()
        anchor_day, anchor_val = disp["days"][-1], disp["values"][-1]
        fc_x = [anchor_day] + fc_days
        fc_median = [anchor_val] + [p["q_median"] for p in fc["points"]]
        fc_p10 = [anchor_val] + [p["q_p10"] for p in fc["points"]]
        fc_p90 = [anchor_val] + [p["q_p90"] for p in fc["points"]]
        # customdata alinhado com fc_x (a ancora e "hoje", nao tem previsao)
        fc_meta = [("hoje", 0.0, anchor_val, anchor_val)] + [
            (f"+{p['horizon']}d", p["trig_prob"], p["q_p10"], p["q_p90"])
            for p in fc["points"]]
        fig.add_trace(go.Scatter(x=fc_x, y=fc_p90, mode="lines",
                                 line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=fc_x, y=fc_p10, mode="lines",
                                 name="Previsão P10–P90", line=dict(width=0),
                                 fill="tonexty", fillcolor="rgba(138,92,59,.16)",
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=fc_x, y=fc_median, mode="lines+markers",
            name="Previsão (mediana ensemble)",
            line=dict(color=FORECAST_COLOR, width=2, dash="dash"),
            marker=dict(size=5),
            customdata=[[m[0], m[1] * 100, m[2], m[3], d]
                        for m, d in zip(fc_meta, [None] + [p["date"] for p in fc["points"]])],
            hovertemplate="<b>%{customdata[0]}</b> (%{customdata[4]})<br>"
                          f"Mediana: %{{y:.1f}} {info['unit']}<br>"
                          f"Faixa provável: %{{customdata[2]:.1f}}–%{{customdata[3]:.1f}} {info['unit']}<br>"
                          "Membros acima do P95: %{customdata[1]:.0f}%<extra></extra>",
        ))
        fig.add_vline(x=anchor_day, line=dict(color=INK_MUTED, width=1, dash="dot"),
                      annotation_text="hoje", annotation_font_size=9)
    fig.update_xaxes(title_text="Data (mm-dd)", tickmode="array",
                     tickvals=SEASON_TICKVALS, ticktext=SEASON_TICKTEXT)
    fig.update_yaxes(title_text=f"{METRIC_LABEL[metric]} ({info['unit']})")
    st.plotly_chart(styled(fig, height=430), width="stretch")
    if fc:
        issued_dt = forecast.get("issued", "")[:16].replace("T", " ")
        st.caption(f"Previsão: ensemble ECMWF (50 membros), modelo rainfall-runoff por "
                  f"estação · emitida {issued_dt} UTC · gatilho de referência P95 = "
                  f"{fc['trig_thr']:.1f} {info['unit']} · risco de cruzá-lo em 15 dias: "
                  f"{fc['trigger_prob_15d'] * 100:.0f}%.")

    with st.expander(f"Ver detalhe do {EXCESS_LABEL[metric].lower()}"):
        env = info["envelope"]
        env_days = list(range(hydro.SEASON_LEN_DAYS))
        fig2 = go.Figure()
        if env["max"]:
            fig2.add_trace(go.Scatter(x=env_days, y=env["max"], mode="lines",
                                      name="Máximo histórico",
                                      line=dict(color="rgba(178,58,46,.30)", width=1)))
            fig2.add_trace(go.Scatter(x=env_days, y=env["p90"], mode="lines", name="P90",
                                      fill="tonexty", fillcolor="rgba(193,101,46,.08)",
                                      line=dict(color="rgba(193,101,46,.45)", width=1)))
            fig2.add_trace(go.Scatter(x=env_days, y=env["p50"], mode="lines", name="Mediana",
                                      fill="tonexty", fillcolor="rgba(140,138,128,.12)",
                                      line=dict(color="rgba(120,118,110,.55)", width=1)))
        if disp["is_current"]:
            s = load_current(code)
            s = s[metric].dropna() if metric in s.columns else pd.Series(dtype=float)
            s = hydro.season_slice(s, status["season_year"])
            curve = hydro.cei_curve(s, info["threshold"])
            if not curve.empty:
                fig2.add_trace(go.Scatter(x=curve.index, y=curve.values, mode="lines",
                                          name=disp["label"], line=dict(color=LINE_BLUE, width=2.2)))
        elif disp["values"]:
            arr = info["seasons"][season_choice]
            cei_vals = hydro.cei_from_aligned(arr, info["threshold"])
            fig2.add_trace(go.Scatter(x=env_days, y=cei_vals, mode="lines",
                                      name=disp["label"], line=dict(color=LINE_BLUE, width=2.2)))
        fig2.update_xaxes(title_text="Data (mm-dd)", tickmode="array",
                          tickvals=SEASON_TICKVALS, ticktext=SEASON_TICKTEXT)
        fig2.update_yaxes(title_text=EXCESS_LABEL[metric])
        st.plotly_chart(styled(fig2, height=280), width="stretch")
        st.caption(f"{EXCESS_LABEL[metric]} = soma dos excessos diários de "
                  f"{METRIC_LABEL[metric].lower()} acima do limiar histórico P97 da "
                  f"própria estação, acumulada ao longo da temporada.")

# --------------------------------------------------------------------------
with tab_forecast:
    if not forecast.get("stations"):
        st.info("Previsão ainda não importada. Rode `etl/import_forecast.py` "
                "(e `etl/import_rain_forecast.py`) a partir do RIVERFLOW.")
    else:
        issued_dt = forecast.get("issued", "")[:16].replace("T", " ")
        st.caption(f"Previsão operacional — ensemble ECMWF (50 membros), ~15 dias · "
                  f"emitida {issued_dt} UTC · atualizada manualmente, não faz parte "
                  f"do job horário de telemetria.")

        st.markdown("**Estações em risco de ultrapassar o P95 nos próximos 15 dias**")
        risk_rows = []
        for code, fc_station in forecast["stations"].items():
            match = df[df["code"] == code]
            if match.empty:
                continue
            m = match.iloc[0]
            for fmetric, fc in fc_station["metrics"].items():
                risk_rows.append({
                    "Estação": m["name"], "Rio": m["river"] or "—",
                    "Métrica": METRIC_LABEL[fmetric],
                    "Prob. 15d (%)": round(fc["trigger_prob_15d"] * 100),
                    "Pico previsto": f"{fc['peak_median']:.1f} {fc['unit']}",
                    "Data do pico": fc["peak_date"],
                })
        risk_df = pd.DataFrame(risk_rows).sort_values("Prob. 15d (%)", ascending=False)
        n_flagged = int((risk_df["Prob. 15d (%)"] >= 30).sum())
        st.caption(f"{n_flagged} de {len(risk_df)} séries (estação × métrica) com "
                  f"probabilidade ≥ 30% de cruzar o P95 (gatilho de referência) em algum "
                  f"dia dos próximos 15 dias — fração dos 50 membros do ensemble que "
                  f"cruzam o limiar. Vazão e nível são previstos separadamente.")
        st.dataframe(
            risk_df, width="stretch", hide_index=True, height=340,
            column_config={
                "Prob. 15d (%)": st.column_config.ProgressColumn(
                    "Prob. 15d (%)", min_value=0, max_value=100, format="%.0f%%"),
            },
        )

        st.write("")
        horizon = rain_forecast.get("horizon_days", 15)
        st.markdown(f"**Chuva acumulada prevista — próximos {horizon} dias "
                   f"(média do ensemble)**")
        rain_map_path = DATA / "rain_map.png"
        if rain_map_path.exists():
            st.image(str(rain_map_path), width="stretch")
            st.caption("Precipitação acumulada média do ensemble ECMWF (50 membros), "
                      "somada dia a dia até o horizonte de 15 dias, krigada a partir da "
                      "grade nativa (~0,25°) e recortada exatamente no contorno do RS "
                      "(IBGE). Escala em faixas fixas (0–300mm), como em mapas "
                      "meteorológicos, pra ler igual em qualquer atualização. É a "
                      "chuva-fonte que alimenta o modelo de vazão/nível de cada estação "
                      "— não é, em si, uma previsão por bacia hidrográfica.")
        else:
            st.info("Mapa de chuva ainda não gerado. Rode `etl/import_rain_forecast.py` "
                    "e depois `etl/render_rain_map.py`.")

# --------------------------------------------------------------------------
with tab_table:
    tbl = df.copy()
    tbl["status"] = tbl["status"].map(STATUS_LABEL)
    tbl = tbl[["code", "name", "river", "municipality", "data_type", "unit",
               "last_date", "last_value", "days_since", "status",
               "cei_now", "cei_pct_rank", "n_seasons"]]
    tbl.columns = ["Código", "Estação", "Rio", "Município", "Tipo", "Un.",
                   "Últ. data", "Últ. valor", "Dias atrás", "Status",
                   "Excesso acumulado", "Excesso rank %", "Temporadas"]
    st.dataframe(tbl, width="stretch", hide_index=True, height=540,
                 column_config={
                     "Excesso rank %": st.column_config.ProgressColumn(
                         "Excesso rank %", min_value=0, max_value=100, format="%.0f%%"),
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
<b>Excesso acumulado (de vazão ou de nível):</b> soma dos excessos diários
acima do percentil P97 da própria estação, acumulada ao longo da
temporada — de vazão para estações medidas em vazão, de nível para as
medidas em nível. Um valor alto significa uma temporada com excedentes
mais frequentes ou intensos que o normal <i>para aquele rio</i> — não é
comparável entre estações diferentes.<br><br>
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
