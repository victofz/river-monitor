"""
build_index.py -- consolida baseline + temporada corrente em data/status.json.

Para cada estacao calcula, comparando SO com o proprio historico:
  - CEI acumulado da temporada corrente
  - rank percentil desse CEI vs. temporadas passadas da estacao
  - status do valor diario mais recente (normal/elevado/alto/extremo)
  - frescor do dado (dias desde a ultima leitura)

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
    start, end = hydro.season_bounds(sy)

    stations_out = []
    counts = {k: 0 for k in hydro.STATUS_LABEL}

    for code in STATIONS:
        info = baseline.get(code)
        if not info:
            continue

        cur_path = CUR_DIR / f"{code}.parquet"
        cur = pd.Series(dtype=float)
        if cur_path.exists():
            cur = pd.read_parquet(cur_path)["value"]
            cur.index = pd.to_datetime(cur.index)
            cur = cur[(cur.index >= start) & (cur.index <= end)].sort_index()

        threshold = info["threshold"]
        if not cur.empty:
            curve = hydro.cei_curve(cur, threshold)
            cei_now = float(curve.iloc[-1]) if not curve.empty else 0.0
            last_date = cur.index.max()
            last_value = float(cur.iloc[-1])
            days_since = int((today - last_date.normalize()).days)
            status = hydro.daily_status(
                last_value, info["p90"], info["p97"], info["p99"])
            elapsed = int(hydro.season_day(pd.DatetimeIndex([last_date]), sy)[0])
        else:
            cei_now, last_date, last_value = 0.0, None, None
            days_since, status, elapsed = None, "sem_dado", None

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
        "in_season": hydro.is_in_season(today),
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
