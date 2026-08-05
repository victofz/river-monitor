"""
seed_baseline.py -- bootstrap unico do historico (roda uma vez).

Le o historico diario completo (ANA HidroWeb) de cada estacao e resume,
para o REPO, tudo o que o dashboard precisa para comparar a temporada
corrente com o proprio passado da estacao:

  - limiar P97 e percentis P50/P90/P97/P99 dos valores diarios (serie
    completa -- a temporada agora cobre o ano inteiro, 1-jul a 30-jun,
    sem periodo "fora de risco")
  - distribuicao dos CEIs totais das temporadas passadas
  - envelope da curva acumulada de CEI (p50/p90/max) por dia-de-temporada
  - envelope do VALOR bruto (vazao/nivel: min/p50/max) por dia-de-temporada
    -- a faixa climatologica usada no grafico de destaque do dashboard
  - metadados (nome, rio, municipio, lat/lon, unidade)

Fonte do historico: um diretorio local com os parquets ANA ja consolidados
(baixados previamente do HidroWeb). Aponte via env ANA_SOURCE_DATA ou
deixe o default ../ana-data.

Saida: data/baseline.json  (commitado -> repo fica auto-suficiente)
       data/current/<code>.parquet  (semente do buffer rolante)
"""
from __future__ import annotations

import json
import os
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hydro  # noqa: E402
from stations import STATIONS  # noqa: E402

RF = Path(os.environ.get("ANA_SOURCE_DATA", "../ana-data")).resolve()
FLOW_DIR = RF / "ana"
COTA_DIR = RF / "water_level"
INV_JSON = FLOW_DIR / "rs_api_inventory.json"
PROP_A = RF / "proposals" / "proposal_a_flow_products.json"
PROP_B = RF / "proposals" / "proposal_b_cota_products.json"

OUT = Path(__file__).resolve().parent.parent / "data"
CUR_DIR = OUT / "current"
OUT.mkdir(exist_ok=True)
CUR_DIR.mkdir(parents=True, exist_ok=True)

MIN_COVERAGE_DAYS = 240  # temporada so conta se tiver cobertura >~65% do ano


def clean_name(s: str) -> str:
    """Remove mojibake/acentos quebrados do inventario e normaliza."""
    if not s:
        return ""
    s = s.replace("�", "")  # remove caractere de substituicao
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.split()).title()


def load_meta() -> dict:
    inv = {}
    if INV_JSON.exists():
        for s in json.loads(INV_JSON.read_text(encoding="utf-8")):
            inv[str(s["codigoestacao"])] = s
    prod = {}
    for jf in (PROP_A, PROP_B):
        if jf.exists():
            for p in json.loads(jf.read_text(encoding="utf-8")):
                prod.setdefault(str(p.get("station_code", "")), p)

    def meta_for(code: str) -> dict:
        s = inv.get(code, {})
        p = prod.get(code, {})
        name = clean_name(p.get("station_name") or s.get("Estacao_Nome") or code)
        river = clean_name(p.get("river") or s.get("Rio_Nome") or "")
        muni = clean_name(p.get("municipality") or s.get("Municipio_Nome") or "")
        try:
            lat = float(s.get("Latitude")) if s.get("Latitude") else None
            lon = float(s.get("Longitude")) if s.get("Longitude") else None
        except (TypeError, ValueError):
            lat = lon = None
        return {"name": name or code, "river": river,
                "municipality": muni, "lat": lat, "lon": lon}

    return {c: meta_for(c) for c in STATIONS}


def load_series(code: str) -> tuple[pd.Series, str, str]:
    """Retorna (serie diaria, data_type, unidade). Prefere vazao; cai p/ nivel."""
    fp = FLOW_DIR / f"flow_{code}.parquet"
    cp = COTA_DIR / f"cota_{code}.parquet"
    if fp.exists():
        df = pd.read_parquet(fp)
        s = df["value"].copy()
        dtype, unit = "flow", "m3/s"
    elif cp.exists():
        df = pd.read_parquet(cp)
        col = "level_cm" if "level_cm" in df.columns else "value"
        s = df[col].copy()
        dtype, unit = "level", "cm"
    else:
        return pd.Series(dtype=float), "none", ""
    s.index = pd.to_datetime(s.index)
    s = s[~s.index.duplicated(keep="first")].sort_index().dropna()
    return s, dtype, unit


def seasonal_data(series: pd.Series, threshold: float):
    """Para cada temporada com cobertura suficiente: curva de CEI (dia 0..365)
    e o valor bruto alinhado por dia-de-temporada (para o envelope min/max)."""
    idx = np.arange(hydro.SEASON_LEN_DAYS)
    cei_curves: dict[int, pd.Series] = {}
    value_rows: list[np.ndarray] = []
    years = range(series.index.year.min() - 1, series.index.year.max() + 1)
    for sy in years:
        seg = hydro.season_slice(series, sy)
        if len(seg) < MIN_COVERAGE_DAYS:
            continue
        curve = hydro.cei_curve(seg, threshold)
        if curve.empty:
            continue
        cei_curves[sy] = curve

        days = hydro.season_day(seg.index, sy)
        raw = pd.Series(seg.values, index=days)
        raw = raw[(raw.index >= 0) & (raw.index < hydro.SEASON_LEN_DAYS)]
        # sem ffill aqui: dia sem leitura fica NaN e e ignorado no min/max
        # (ffill faria sentido para uma serie acumulada, nao para o valor bruto)
        value_rows.append(raw.reindex(idx).to_numpy(dtype=float))
    return cei_curves, value_rows


def build_cei_envelope(curves: dict[int, pd.Series]) -> dict:
    """Matriz dia x temporada (CEI acumulado) -> percentis p50/p90/max."""
    if not curves:
        return {"p50": [], "p90": [], "max": []}
    idx = np.arange(hydro.SEASON_LEN_DAYS)
    mat = np.full((len(curves), hydro.SEASON_LEN_DAYS), np.nan)
    for i, curve in enumerate(curves.values()):
        aligned = curve.reindex(idx).ffill().fillna(0.0)
        mat[i] = aligned.values
    return {
        "p50": np.nanpercentile(mat, 50, axis=0).round(2).tolist(),
        "p90": np.nanpercentile(mat, 90, axis=0).round(2).tolist(),
        "max": np.nanmax(mat, axis=0).round(2).tolist(),
    }


def build_value_envelope(value_rows: list[np.ndarray]) -> dict:
    """Matriz dia x temporada (valor bruto) -> faixa climatologica min/p50/max."""
    if not value_rows:
        return {"min": [], "p50": [], "max": []}
    mat = np.vstack(value_rows)
    with np.errstate(all="ignore"):
        vmin = np.nanmin(mat, axis=0)
        vp50 = np.nanmedian(mat, axis=0)
        vmax = np.nanmax(mat, axis=0)
    # dias sem NENHUMA temporada com dado viram NaN -> None (json null)
    def clean(arr):
        return [None if np.isnan(v) else round(float(v), 2) for v in arr]
    return {"min": clean(vmin), "p50": clean(vp50), "max": clean(vmax)}


def main() -> None:
    if not FLOW_DIR.exists():
        sys.exit(f"Dados nao encontrados em {RF}. "
                 f"Defina ANA_SOURCE_DATA apontando para um diretorio com "
                 f"os parquets ANA (subpastas ana/ e water_level/).")

    meta = load_meta()
    baseline = {}
    today = pd.Timestamp.today().normalize()
    cur_sy = hydro.display_season_year(today)
    cur_start, _ = hydro.season_bounds(cur_sy)

    print(f"Seed baseline | fonte: {RF}")
    print(f"Temporada corrente para semente: {cur_sy}/{cur_sy+1}")
    print("=" * 64)

    for i, code in enumerate(STATIONS, 1):
        series, dtype, unit = load_series(code)
        if series.empty:
            print(f"[{i:2d}/50] {code}  SEM DADOS -- pulado")
            continue

        p50, p90, p97, p99 = np.percentile(
            series.values, [50, 90, hydro.THRESHOLD_PCT, 99])
        threshold = float(p97)

        cei_curves, value_rows = seasonal_data(series, threshold)
        totals = sorted(float(c.iloc[-1]) for c in cei_curves.values())
        cei_envelope = build_cei_envelope(cei_curves)
        value_envelope = build_value_envelope(value_rows)

        baseline[code] = {
            **meta[code],
            "data_type": dtype,
            "unit": unit,
            "threshold": round(threshold, 3),
            "p50": round(float(p50), 3),
            "p90": round(float(p90), 3),
            "p97": round(float(p97), 3),
            "p99": round(float(p99), 3),
            "record_start": str(series.index.min().date()),
            "record_end": str(series.index.max().date()),
            "n_seasons": len(cei_curves),
            "seasonal_totals": [round(t, 2) for t in totals],
            "envelope": cei_envelope,
            "value_envelope": value_envelope,
        }

        # semente do buffer rolante (sem corte no fim -- ver fetch_telemetry.py)
        cur = series[series.index >= cur_start]
        if not cur.empty:
            pd.DataFrame({"value": cur}).to_parquet(CUR_DIR / f"{code}.parquet")

        print(f"[{i:2d}/50] {code}  {baseline[code]['name'][:22]:22s} "
              f"{dtype:5s} P97={threshold:8.1f} temporadas={len(cei_curves):2d} "
              f"seed={len(cur)}d")

    (OUT / "baseline.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=" * 64)
    print(f"OK -> data/baseline.json  ({len(baseline)} estacoes)")
    print(f"OK -> data/current/*.parquet  (semente temporada {cur_sy}/{cur_sy+1})")


if __name__ == "__main__":
    main()
