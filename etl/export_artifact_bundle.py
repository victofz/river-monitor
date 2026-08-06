"""
export_artifact_bundle.py -- exporta um pacote JS compacto para o Claude Artifact.

O Artifact e uma pagina estatica auto-contida (sem backend, sem chamadas
externas): nao pode ler data/*.parquet nem rodar Python. Este script gera
um UNICO objeto JS com tudo que a pagina precisa -- um retrato ("snapshot")
dos dados no momento da exportacao, reaproveitando os mesmos numeros que
o dashboard Streamlit ja calculou (status.json/baseline.json), para nao
haver logica duplicada nem divergencia entre as duas paginas.

Saida: scratch/artifact_bundle.js  (const BUNDLE = {...};)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hydro  # noqa: E402
from stations import STATIONS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "scratch"
OUT.mkdir(exist_ok=True)


def season_series(code: str, metric: str, season_year: int) -> list[list[float]]:
    p = DATA / "current" / f"{code}.parquet"
    if not p.exists():
        return []
    df = pd.read_parquet(p)
    if metric not in df.columns:
        return []
    s = df[metric].dropna()
    s.index = pd.to_datetime(s.index)
    s = hydro.season_slice(s, season_year).sort_index()
    if s.empty:
        return []
    days = hydro.season_day(s.index, season_year)
    return [[int(d), round(float(v), 1)] for d, v in zip(days, s.values)]


def round_env(arr: list[float], nd: int) -> list[float]:
    return [round(float(v), nd) for v in arr]


def main() -> None:
    status = json.loads((DATA / "status.json").read_text(encoding="utf-8"))
    baseline = json.loads((DATA / "baseline.json").read_text(encoding="utf-8"))
    by_code = {s["code"]: s for s in status["stations"]}

    stations_out = []
    for code in STATIONS:
        st = by_code.get(code)
        bl = baseline.get(code)
        if not st or not bl:
            continue
        primary = bl["primary_metric"]
        m = bl["metrics"][primary]
        # precisao de arredondamento por unidade (m3/s tende a ter mais digitos)
        nd = 1 if m["unit"] == "cm" else 1
        env = m["envelope"]
        stations_out.append({
            "code": code,
            "name": st["name"],
            "river": st["river"],
            "municipality": st["municipality"],
            "lat": st["lat"],
            "lon": st["lon"],
            "dataType": st["data_type"],
            "unit": st["unit"],
            "threshold": m["threshold"],
            "p50": m["p50"],
            "p90": st["p90"],
            "p97": st["p97"],
            "p99": st["p99"],
            "recordStart": m["record_start"],
            "nSeasons": st["n_seasons"],
            "status": st["status"],
            "lastDate": st["last_date"],
            "lastValue": st["last_value"],
            "daysSince": st["days_since"],
            "ceiNow": st["cei_now"],
            "ceiPctRank": st["cei_pct_rank"],
            "seasonDay": st["season_day"],
            "season": season_series(code, primary, status["season_year"]),
            "envelope": {
                "p50": round_env(env["p50"], nd),
                "p90": round_env(env["p90"], nd),
                "max": round_env(env["max"], nd),
            },
        })

    bundle = {
        "updatedUtc": status["updated_utc"],
        "seasonYear": status["season_year"],
        "seasonLabel": status["season_label"],
        "nStations": status["n_stations"],
        "nFresh": status["n_fresh"],
        "statusCounts": status["status_counts"],
        "stations": stations_out,
    }

    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")  # seguranca ao embutir em <script>
    js = f"const BUNDLE = {payload};\n"
    out_path = OUT / "artifact_bundle.js"
    out_path.write_text(js, encoding="utf-8")

    print(f"OK -> {out_path}  ({len(js)/1024:.1f} KB, {len(stations_out)} estacoes)")


if __name__ == "__main__":
    main()
