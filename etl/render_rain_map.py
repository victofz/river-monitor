"""
render_rain_map.py -- gera um PNG cartografico da chuva acumulada prevista
(a partir de data/rain_forecast.json, ja krigado por import_rain_forecast.py),
recortado exatamente no contorno oficial do RS (IBGE via geobr), com o
contorno desenhado POR CIMA do preenchimento, legenda em faixas, norte,
escala e um mini-mapa de localizacao do Brasil -- no estilo de um mapa
meteorologico/cartografico "de verdade" (INMET/CPTEC), em vez do mapa
interativo (que so conseguia aproximar o contorno do estado por um casco
convexo das estacoes, sem fronteira real, e sobrepunha mal as divisas).

So roda LOCAL (matplotlib/geopandas/geobr sao pesados demais pro
requirements.txt do app) -- precisa: pip install geobr geopandas matplotlib
(baixa o contorno do RS e do Brasil do IBGE via GitHub na primeira vez,
depois fica em cache local do geobr).

Rode depois de import_rain_forecast.py:
  python etl/render_rain_map.py

Saida: data/rain_map.png  (lido pelo app.py via st.image)
"""
from __future__ import annotations

import json
from pathlib import Path

import geobr
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath

ROOT = Path(__file__).resolve().parent.parent
RAIN_JSON = ROOT / "data" / "rain_forecast.json"
OUT_PNG = ROOT / "data" / "rain_map.png"

RAIN_BREAKS = [0, 10, 25, 50, 75, 100, 150, 200, 300]
RAIN_COLORS = ["#EDF5E8", "#B7E0A5", "#4CAF50", "#E8DE4A",
               "#F2A73B", "#E8622C", "#C41E24", "#7A1E63"]


def polygon_to_path(geom) -> MplPath:
    """Shapely Polygon/MultiPolygon -> matplotlib Path (com buracos)."""
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    verts, codes = [], []
    for poly in polys:
        rings = [poly.exterior] + list(poly.interiors)
        for ring in rings:
            pts = np.asarray(ring.coords)
            verts.extend(pts)
            codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(pts) - 2) + [MplPath.CLOSEPOLY])
    return MplPath(verts, codes)


def draw_north_arrow(ax, x, y, size=0.05):
    ax.annotate("N", xy=(x, y + size), xytext=(x, y - size),
                xycoords="axes fraction", textcoords="axes fraction",
                ha="center", va="center", fontsize=11, fontweight="bold",
                arrowprops=dict(arrowstyle="-|>", color="black", lw=1.6))


def draw_scale_bar(ax, lat_ref, km=100):
    """Barra de escala aproximada (graus->km na latitude media do RS),
    canto inferior direito (esquerdo e ocupado pela legenda)."""
    km_per_deg_lon = 111.32 * np.cos(np.radians(lat_ref))
    deg = km / km_per_deg_lon
    x1, y0 = ax.get_xlim()[1] - 0.45, ax.get_ylim()[0] + 0.35
    x0 = x1 - deg
    ax.plot([x0, x1], [y0, y0], color="black", lw=2, solid_capstyle="butt")
    ax.plot([x0, x0], [y0 - 0.04, y0 + 0.04], color="black", lw=1.2)
    ax.plot([x1, x1], [y0 - 0.04, y0 + 0.04], color="black", lw=1.2)
    ax.text((x0 + x1) / 2, y0 + 0.08, f"{km} km", ha="center", va="bottom", fontsize=8)


def main() -> None:
    if not RAIN_JSON.exists():
        raise SystemExit(f"Nao encontrei {RAIN_JSON}. Rode etl/import_rain_forecast.py primeiro.")

    rf = json.loads(RAIN_JSON.read_text(encoding="utf-8"))
    rain_df = pd.DataFrame(rf["points"])

    print("Baixando/lendo contorno do RS e do Brasil (geobr, cache local apos 1a vez)...")
    rs = geobr.read_state(code_state="RS", year=2020)
    brazil = geobr.read_country(year=2020)
    rs_geom = rs.geometry.iloc[0]
    clip_path = polygon_to_path(rs_geom)

    cmap = plt.matplotlib.colors.ListedColormap(RAIN_COLORS)
    norm = plt.matplotlib.colors.BoundaryNorm(RAIN_BREAKS, cmap.N)

    fig, ax = plt.subplots(figsize=(7.5, 8.5), dpi=150)
    fig.subplots_adjust(left=0.1, right=0.96, top=0.80, bottom=0.07)

    cs = ax.tricontourf(rain_df["lon"], rain_df["lat"], rain_df["mm"],
                        levels=RAIN_BREAKS, cmap=cmap, norm=norm, extend="max")
    patch = PathPatch(clip_path, facecolor="none", edgecolor="none")
    ax.add_patch(patch)
    cs.set_clip_path(patch)

    # contorno do estado POR CIMA do preenchimento
    rs.boundary.plot(ax=ax, color="#1A1A1A", linewidth=1.3, zorder=5)

    bounds = rs_geom.bounds  # minx, miny, maxx, maxy
    pad = 0.35
    ax.set_xlim(bounds[0] - pad, bounds[2] + pad)
    ax.set_ylim(bounds[1] - pad, bounds[3] + pad)
    ax.set_aspect(1 / np.cos(np.radians((bounds[1] + bounds[3]) / 2)))

    ax.grid(True, color="#B0B0B0", linewidth=0.4, linestyle="-", alpha=0.6)
    ax.set_xticks(np.arange(-58, -49, 1))
    ax.set_yticks(np.arange(-34, -26, 1))
    ax.set_xticklabels([f"{abs(t):.0f}W" for t in ax.get_xticks()], fontsize=8)
    ax.set_yticklabels([f"{abs(t):.0f}S" for t in ax.get_yticks()], fontsize=8)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("#333333")

    horizon = rf.get("horizon_days", 15)
    issued = rf.get("issued", "")[:10]
    ax.set_title(f"CHUVA ACUMULADA PREVISTA — PRÓXIMOS {horizon} DIAS\n"
                f"[ENSEMBLE ECMWF, EMITIDO {issued}]",
                fontsize=11, fontweight="bold", pad=14)

    # legenda em faixas
    handles = [plt.matplotlib.patches.Patch(
        facecolor=RAIN_COLORS[i], edgecolor="#333333", linewidth=.4,
        label=f"{RAIN_BREAKS[i]} a {RAIN_BREAKS[i+1]}mm" if i < len(RAIN_BREAKS) - 2
              else f">{RAIN_BREAKS[i]}mm")
        for i in range(len(RAIN_COLORS))]
    ax.legend(handles=handles, loc="lower left", fontsize=7.5, title="mm acumulados",
             title_fontsize=8, framealpha=0.92, borderpad=0.8)

    draw_north_arrow(ax, x=0.94, y=0.90)
    draw_scale_bar(ax, lat_ref=(bounds[1] + bounds[3]) / 2)

    # rotulos de bacia/regiao -- orientacao espacial (sem shapefile de bacias)
    regions = [
        ("Bacia do Uruguai", -27.6, -53.3),
        ("Serra / Taquari-Antas", -29.0, -51.2),
        ("Bacia do Guaíba / Jacuí", -30.0, -52.2),
        ("Litoral / Lagoa dos Patos", -31.6, -51.6),
        ("Fronteira Oeste / Ibicuí", -29.6, -55.8),
        ("Missões / Planalto Médio", -28.0, -54.5),
    ]
    for name, lat, lon in regions:
        ax.text(lon, lat, name, fontsize=7, ha="center", va="center",
                color="#1A1A1A", zorder=6,
                bbox=dict(facecolor="white", alpha=.55, edgecolor="none", pad=1.2))

    # mini-mapa de localizacao (Brasil com o RS destacado) -- fora da faixa
    # do titulo (top=0.80), senao fica desenhado por cima do texto
    inset = fig.add_axes([0.015, 0.84, 0.18, 0.145])
    brazil.boundary.plot(ax=inset, color="#888888", linewidth=.5)
    rs.plot(ax=inset, color="#C41E24")
    inset.set_xticks([]); inset.set_yticks([])
    for spine in inset.spines.values():
        spine.set_visible(False)

    fig.text(0.5, 0.01, "Fonte: precipitação — ensemble ECMWF (50 membros), krigada; "
            "contorno — IBGE (geobr). Elaboração: RS River Monitor.",
            ha="center", fontsize=6.5, color="#555555")

    fig.savefig(OUT_PNG, facecolor="white")
    plt.close(fig)
    print(f"OK -> {OUT_PNG}")


if __name__ == "__main__":
    main()
