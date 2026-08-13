"""
import_rain_forecast.py -- importa a grade de precipitacao acumulada prevista
(media do ensemble ECMWF, ~15 dias, RS inteiro) gerada pelo RIVERFLOW, kriga
pra uma grade mais fina e escreve o schema compacto que o app.py consome
(data/rain_forecast.json). Roda MANUALMENTE, junto com import_forecast.py --
mesma logica: o processamento pesado (leitura do grib de ~755MB) roda no
RIVERFLOW, aqui so se converte e se interpola.

A krigagem (pykrige, ordinary kriging, variograma esferico) so serve pra
suavizar a grade nativa do ECMWF (~0.25 grau, ~1300 pontos) pra algo com
cara de mapa meteorologico -- nao inventa dado novo, so interpola entre os
pontos que ja existem. Precisa de `pip install pykrige` (so aqui, nao entra
no requirements.txt do app -- isso roda uma vez local, o app so le o JSON
ja pronto).

Rode de novo sempre que quiser atualizar o mapa de chuva do dashboard:
  python etl/import_rain_forecast.py

Fonte (aponte via env RIVERFLOW_FORECAST_SOURCE se o layout for outro):
  <fonte>/rain_forecast_grid.csv   lat,lon,mm_15d,mm_15d_p10,mm_15d_p90
  <fonte>/live_ensemble.csv        (so pra reaproveitar o "issued")
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get(
    "RIVERFLOW_FORECAST_SOURCE", "../RIVERFLOW/data/ecmwf_forecast")).resolve()
GRID_CSV = SRC / "rain_forecast_grid.csv"
ALERT_JSON = SRC / "alert_latest.json"

OUT_PATH = ROOT / "data" / "rain_forecast.json"
BASELINE_PATH = ROOT / "data" / "baseline.json"

# grade de saida (graus) -- mais fina que a nativa do ECMWF (0.25) so pra dar
# um acabamento suave; nao e resolucao "real" alem da fonte
OUT_RES_DEG = 0.12

# sem shapefile oficial do RS a mao -- aproxima o contorno do estado pelo
# casco convexo das 50 estacoes monitoradas, expandido a partir do centroide
# (estacoes nao chegam exatamente na fronteira). Corta o retangulo bruto do
# ECMWF (que cobre pedaco de AR/PY/UY/SC/oceano) pra nao pintar chuva fora do RS.
HULL_EXPAND = 1.35


def points_in_polygon(xy: np.ndarray, poly: np.ndarray) -> np.ndarray:
    """Ray casting (sem dependencia extra) -- xy (N,2), poly (M,2) fechado
    implicitamente (ultimo vertice liga ao primeiro)."""
    x, y = xy[:, 0], xy[:, 1]
    inside = np.zeros(len(xy), dtype=bool)
    n = len(poly)
    px, py = poly[:, 0], poly[:, 1]
    for i in range(n):
        x1, y1 = px[i], py[i]
        x2, y2 = px[(i + 1) % n], py[(i + 1) % n]
        crosses = ((y1 > y) != (y2 > y))
        with np.errstate(divide="ignore", invalid="ignore"):
            x_at_y = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        flip = crosses & (x < x_at_y)
        inside[flip] = ~inside[flip]
    return inside


def clip_to_station_hull(df: pd.DataFrame) -> pd.DataFrame:
    from scipy.spatial import ConvexHull

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    pts = np.array([[v["lon"], v["lat"]] for v in baseline.values()
                    if v.get("lat") and v.get("lon")])
    hull = pts[ConvexHull(pts).vertices]
    centroid = hull.mean(axis=0)
    hull_expanded = centroid + (hull - centroid) * HULL_EXPAND

    inside = points_in_polygon(df[["lon", "lat"]].values, hull_expanded)
    return df[inside].reset_index(drop=True)


def krige_grid(df: pd.DataFrame) -> pd.DataFrame:
    from pykrige.ok import OrdinaryKriging

    lon_min, lon_max = df["lon"].min(), df["lon"].max()
    lat_min, lat_max = df["lat"].min(), df["lat"].max()
    grid_lon = np.arange(lon_min, lon_max + OUT_RES_DEG, OUT_RES_DEG)
    grid_lat = np.arange(lat_min, lat_max + OUT_RES_DEG, OUT_RES_DEG)

    ok = OrdinaryKriging(
        df["lon"].values, df["lat"].values, df["mm_15d"].values,
        variogram_model="spherical", verbose=False, enable_plotting=False,
    )
    z, _ = ok.execute("grid", grid_lon, grid_lat)
    z = np.clip(np.asarray(z), 0, None)  # chuva acumulada nao pode ser negativa

    LON, LAT = np.meshgrid(grid_lon, grid_lat)
    return pd.DataFrame({"lat": LAT.ravel(), "lon": LON.ravel(), "mm_15d": z.ravel()})


def main() -> None:
    if not GRID_CSV.exists():
        raise SystemExit(f"Nao encontrei {GRID_CSV}. Rode _export_rain_forecast_grid.py "
                         f"no RIVERFLOW primeiro, ou aponte RIVERFLOW_FORECAST_SOURCE.")

    raw = pd.read_csv(GRID_CSV)
    df = krige_grid(raw)
    df = clip_to_station_hull(df)

    issued = None
    if ALERT_JSON.exists():
        issued = json.loads(ALERT_JSON.read_text(encoding="utf-8")).get("issued")
    if not issued:
        issued = pd.Timestamp.fromtimestamp(GRID_CSV.stat().st_mtime).isoformat()

    out = {
        "issued": issued,
        "horizon_days": 15,
        "points": [
            {"lat": round(float(r.lat), 3), "lon": round(float(r.lon), 3),
             "mm": round(float(r.mm_15d), 1)}
            for r in df.itertuples()
        ],
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    print(f"OK -> {OUT_PATH}  ({len(raw)} pontos nativos -> {len(df)} krigados, "
          f"{df['mm_15d'].min():.0f}-{df['mm_15d'].max():.0f}mm, emitido {issued})")


if __name__ == "__main__":
    main()
