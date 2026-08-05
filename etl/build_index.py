"""
build_index.py -- consolida baseline + buffer rolante em data/status.json.

A temporada e um ciclo continuo de 12 meses (1-jul a 30-jun) -- nao ha
mais gap/entressafra: jul-set e o inicio da propria temporada corrente.

Para cada estacao calcula, comparando SO com o proprio historico:
  - status/valor/data da leitura mais recente -- sobre a serie bruta
    (data/current/<code>.parquet)
  - CEI acumulado da temporada corrente (recorte 1-jul a 30-jun)
  - rank percentil desse CEI vs. temporadas passadas da estacao

Saida: data/status.json  (consumido pelo app.py)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hydro  # noqa: E402
from stations import STATIONS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CUR_DIR = DATA / "current"


def pct_rank(value: float, distribution: list[float]) -> float:
    """% das temporadas passadas com CEI <= value (0..100)."""
    if not distribution:
        return float("nan")
    arr = np.asarray(distribution, dtype=float)
    return float((arr <= value).mean() * 100.0)


def main() -> None:
    baseline = json.loads((DATA / "baseline.json").read_text(encoding="utf-8"))
    today = pd.Timestamp.today().normalize()
    sy = hydro.display_season_year(today)

    stations_out = []
    counts = {k: 0 for k in hydro.STATUS_LABEL}

    for code in STATIONS:
        info = baseline.get(code)
        if not info:
            continue

        cur_path = CUR_DIR / f"{code}.parquet"
        full = pd.Series(dtype=float)
        if cur_path.exists():
            full = pd.read_parquet(cur_path)["value"]
            full.index = pd.to_datetime(full.index)
            full = full.sort_index()

        threshold = info["threshold"]

        # leitura mais recente: serie bruta (nao recortada) -- valida o ano
        # todo, inclusive fora do periodo de risco
        if not full.empty:
            last_date = full.index.max()
            last_value = float(full.iloc[-1])
            days_since = int((today - last_date.normalize()).days)
            status = hydro.daily_status(
                last_value, info["p90"], info["p97"], info["p99"])
        else:
            last_date, last_value, days_since, status = None, None, None, "sem_dado"

        # CEI: somente dentro do recorte out-jun -- fora da temporada, fica
        # congelado no valor final da ultima temporada encerrada
        season_view = hydro.season_slice(full, sy) if not full.empty else full
        if not season_view.empty:
            curve = hydro.cei_curve(season_view, threshold)
            cei_now = float(curve.iloc[-1]) if not curve.empty else 0.0
            elapsed = int(hydro.season_day(
                pd.DatetimeIndex([season_view.index.max()]), sy)[0])
        else:
            cei_now, elapsed = 0.0, None

        counts[status] += 1
        stations_out.append({
            "code": code,
            "name": info["name"],
            "river": info["river"],
            "municipality": info["municipality"],
            "lat": info["lat"],
            "lon": info["lon"],
            "data_type": info["data_type"],
            "unit": info["unit"],
            "threshold": threshold,
            "p90": info["p90"], "p97": info["p97"], "p99": info["p99"],
            "n_seasons": info["n_seasons"],
            "last_date": str(last_date.date()) if last_date is not None else None,
            "last_value": round(last_value, 2) if last_value is not None else None,
            "days_since": days_since,
            "status": status,
            "cei_now": round(cei_now, 2),
            "cei_pct_rank": round(pct_rank(cei_now, info["seasonal_totals"]), 1),
            "season_day": elapsed,
        })

    fresh = sum(1 for s in stations_out
                if s["days_since"] is not None and s["days_since"] <= 2)
    status_json = {
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "season_year": sy,
        "season_label": f"{sy}/{str(sy + 1)[-2:]}",
        "n_stations": len(stations_out),
        "n_fresh": fresh,
        "status_counts": counts,
        "stations": stations_out,
    }
    (DATA / "status.json").write_text(
        json.dumps(status_json, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"OK -> data/status.json | temporada {status_json['season_label']} "
          f"| {len(stations_out)} estacoes | {fresh} com dado fresco")
    print("  status:", {k: v for k, v in counts.items() if v})


if __name__ == "__main__":
    main()
