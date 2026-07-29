"""
seed_baseline.py -- bootstrap unico do historico (roda uma vez).

Le o historico diario completo (ANA HidroWeb) de cada estacao e resume,
para o REPO, tudo o que o dashboard precisa para comparar a temporada
corrente com o proprio passado da estacao:

  - limiar P97 e percentis P50/P90/P97/P99 dos valores diarios em periodo de risco
  - distribuicao dos CEIs totais das temporadas passadas
  - envelope (p50/p90/max) da curva acumulada de CEI ao longo da temporada
  - metadados (nome, rio, municipio, lat/lon, unidade)

Fonte do historico: repositorio RIVERFLOW (parquets ANA ja consolidados).
Aponte via env RIVERFLOW_DATA ou deixe o default ../RIVERFLOW/data.

Saida: data/baseline.json  (commitado -> repo fica auto-suficiente)
       data/current/<code>.parquet  (semente da temporada corrente)
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

RF = Path(os.environ.get("RIVERFLOW_DATA", "../RIVERFLOW/data")).resolve()
FLOW_DIR = RF / "ana"
COTA_DIR = RF / "water_level"
INV_JSON = FLOW_DIR / "rs_api_inventory.json"
PROP_A = RF / "proposals" / "proposal_a_flow_products.json"
PROP_B = RF / "proposals" / "proposal_b_cota_products.json"

OUT = Path(__file__).resolve().parent.parent / "data"
CUR_DIR = OUT / "current"
OUT.mkdir(exist_ok=True)
CUR_DIR.mkdir(parents=True, exist_ok=True)

MIN_COVERAGE_DAYS = 180  # temporada so conta se tiver >=180 dias em risco


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


def seasonal_curves(series: pd.Series, threshold: float) -> dict[int, pd.Series]:
    """Curva de CEI (dia 0..272) para cada temporada com cobertura suficiente."""
    curves = {}
    years = range(series.index.year.min() - 1, series.index.year.max() + 1)
    for sy in years:
        seg = hydro.season_slice(series, sy)
        if len(seg) < MIN_COVERAGE_DAYS:
            continue
        curve = hydro.cei_curve(seg, threshold)
        if not curve.empty:
            curves[sy] = curve
    return curves


def build_envelope(curves: dict[int, pd.Series]) -> dict:
    """Matriz dia x temporada -> percentis p50/p90/max por dia da temporada."""
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


def main() -> None:
    if not FLOW_DIR.exists():
        sys.exit(f"RIVERFLOW data nao encontrado em {RF}. "
                 f"Defina RIVERFLOW_DATA apontando para .../RIVERFLOW/data")

    meta = load_meta()
    baseline = {}
    today = pd.Timestamp.today().normalize()
    cur_sy = hydro.display_season_year(today)
    cur_start, cur_end = hydro.season_bounds(cur_sy)

    print(f"Seed baseline | fonte: {RF}")
    print(f"Temporada corrente para semente: {cur_sy}/{cur_sy+1}")
    print("=" * 64)

    for i, code in enumerate(STATIONS, 1):
        series, dtype, unit = load_series(code)
        if series.empty:
            print(f"[{i:2d}/50] {code}  SEM DADOS -- pulado")
            continue

        inseason = hydro.in_season(series)
        if inseason.empty:
            print(f"[{i:2d}/50] {code}  sem dados em periodo de risco -- pulado")
            continue

        p50, p90, p97, p99 = np.percentile(
            inseason.values, [50, 90, hydro.THRESHOLD_PCT, 99])
        threshold = float(p97)

        curves = seasonal_curves(series, threshold)
        totals = sorted(float(c.iloc[-1]) for c in curves.values())
        envelope = build_envelope(curves)

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
            "n_seasons": len(curves),
            "seasonal_totals": [round(t, 2) for t in totals],
            "envelope": envelope,
        }

        # semente da temporada corrente (o que ja existe no historico)
        cur = series[(series.index >= cur_start) & (series.index <= min(cur_end, today))]
        if not cur.empty:
            pd.DataFrame({"value": cur}).to_parquet(CUR_DIR / f"{code}.parquet")

        print(f"[{i:2d}/50] {code}  {baseline[code]['name'][:22]:22s} "
              f"{dtype:5s} P97={threshold:8.1f} temporadas={len(curves):2d} "
              f"seed={len(cur)}d")

    (OUT / "baseline.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=" * 64)
    print(f"OK -> data/baseline.json  ({len(baseline)} estacoes)")
    print(f"OK -> data/current/*.parquet  (semente temporada {cur_sy}/{cur_sy+1})")


if __name__ == "__main__":
    main()
