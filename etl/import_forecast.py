"""
import_forecast.py -- importa o forecast operacional do RIVERFLOW (ensemble
ECMWF, ~15 dias, 50 membros) para uma pasta local, roda MANUALMENTE (nao faz
parte do job horario do GitHub Actions).

O forecast e pesado pra rodar em CI publico (~755MB de grib, ~10min de
retreino, credenciais CDS privadas) -- ele roda 4x/dia numa tarefa agendada
LOCAL no RIVERFLOW (Windows Task Scheduler) e escreve
data/ecmwf_forecast/live_ensemble.csv. Este script so LE esse CSV ja pronto
e converte pro schema compacto que o app.py consome (data/forecast.json).

Rode de novo sempre que quiser atualizar a previsao exibida no dashboard:
  python etl/import_forecast.py

Fonte (aponte via env RIVERFLOW_FORECAST_SOURCE se o layout for outro):
  <fonte>/live_ensemble.csv
    code,name,target,unit,horizon,date,q_median,q_p10,q_p90,trig_prob,trig_thr

A coluna `target` diz a metrica prevista ("flow"/"level") -- o RIVERFLOW
preve as DUAS quando a estacao tem as duas, entao cada estacao pode ter
duas series aqui. Guardamos indexado por metrica ("metrics"), pra o app
casar com a metrica que o usuario escolheu ver.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(os.environ.get(
    "RIVERFLOW_FORECAST_SOURCE", "../RIVERFLOW/data/ecmwf_forecast")).resolve()
LIVE_CSV = SRC / "live_ensemble.csv"
ALERT_JSON = SRC / "alert_latest.json"

OUT_PATH = ROOT / "data" / "forecast.json"
BASELINE_PATH = ROOT / "data" / "baseline.json"


def main() -> None:
    if not LIVE_CSV.exists():
        raise SystemExit(f"Nao encontrei {LIVE_CSV}. Rode _forecast_cron.py no "
                         f"RIVERFLOW primeiro, ou aponte RIVERFLOW_FORECAST_SOURCE.")

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    df = pd.read_csv(LIVE_CSV, dtype={"code": str})

    issued = None
    if ALERT_JSON.exists():
        issued = json.loads(ALERT_JSON.read_text(encoding="utf-8")).get("issued")
    if not issued:
        issued = pd.Timestamp.fromtimestamp(LIVE_CSV.stat().st_mtime).isoformat()

    stations = {}
    for code, g in df.groupby("code"):
        station = baseline.get(code)
        if not station:
            continue  # fora do painel do monitor (ex.: painel de forecast != painel RS)

        metrics = {}
        for metric, gm in g.groupby("target"):
            if metric not in station["metrics"]:
                continue  # metrica que o monitor nao acompanha nessa estacao
            gm = gm.sort_values("horizon")
            points = [{
                "horizon": int(row["horizon"]),
                "date": str(row["date"]),
                "q_median": round(float(row["q_median"]), 2),
                "q_p10": round(float(row["q_p10"]), 2),
                "q_p90": round(float(row["q_p90"]), 2),
                "trig_prob": round(float(row["trig_prob"]), 3),
            } for _, row in gm.iterrows()]

            # risco: maior prob. de cruzar o gatilho P95 em qualquer horizonte
            # ate 15d, e o pico (mediana) previsto -- mesma definicao do
            # trigger_prob_15d do alert_latest.json do RIVERFLOW, recalculada
            # aqui pra cobrir TODAS as estacoes (o alert so lista as
            # sinalizadas/top10, nao o painel inteiro)
            peak_row = gm.loc[gm["q_median"].idxmax()]
            risk_row = gm.loc[gm["trig_prob"].idxmax()]
            metrics[metric] = {
                "unit": str(gm["unit"].iloc[0]),
                "trig_thr": round(float(gm["trig_thr"].iloc[0]), 2),
                "trigger_prob_15d": round(float(risk_row["trig_prob"]), 3),
                "trigger_horizon": int(risk_row["horizon"]),
                "peak_median": round(float(peak_row["q_median"]), 2),
                "peak_date": str(peak_row["date"]),
                "points": points,
            }

        if metrics:
            stations[code] = {"primary_metric": station["primary_metric"],
                              "metrics": metrics}

    out = {"issued": issued, "trig_pct": 95, "stations": stations}
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    n_series = sum(len(s["metrics"]) for s in stations.values())
    print(f"OK -> {OUT_PATH}  ({len(stations)} estacoes / {n_series} series, "
          f"emitido {issued})")


if __name__ == "__main__":
    main()
