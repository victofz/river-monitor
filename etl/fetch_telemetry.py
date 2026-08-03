"""
fetch_telemetry.py -- busca telemetria em tempo real da ANA (roda 1x/dia).

Baixa as leituras sub-diarias (~15 min) das 50 estacoes via SOAP,
agrega para media diaria e atualiza data/current/<code>.parquet -- um
buffer rolante (ultimos KEEP_DAYS dias), NAO recortado por temporada.
O recorte out-jun (para o CEI) e feito na leitura, em build_index.py e
app.py -- assim a leitura mais recente fica sempre disponivel mesmo na
entressafra (jul-set), quando a temporada de risco esta fechada.

Robusto por design:
  - falha por estacao nao derruba o job;
  - se a fracao de estacoes com sucesso for baixa, sai com codigo != 0
    para o workflow NAO commitar dados possivelmente corrompidos.
"""
from __future__ import annotations

import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hydro  # noqa: E402
from stations import STATIONS  # noqa: E402

SOAP_URL = "http://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
XML_TAG = "DadosHidrometereologicos"  # typo original da ANA -- manter

CUR_DIR = Path(__file__).resolve().parent.parent / "data" / "current"
CUR_DIR.mkdir(parents=True, exist_ok=True)

LOOKBACK_DAYS = 45          # janela buscada a cada rodada
KEEP_DAYS = 450             # buffer rolante guardado no parquet (~15 meses)
MIN_SUCCESS_FRACTION = 0.5  # < isto => aborta sem commit


def fetch(code: str, start: str, end: str) -> pd.DataFrame:
    params = {"codEstacao": code, "dataInicio": start, "dataFim": end}
    r = requests.get(SOAP_URL, params=params, timeout=120)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    rows = []
    for rec in root.iter(XML_TAG):
        rows.append({c.tag.split("}")[-1]: c.text for c in rec})
    return pd.DataFrame(rows)


def to_daily(df: pd.DataFrame, data_type: str) -> pd.Series:
    """Agrega telemetria bruta para serie diaria (media) do tipo relevante."""
    if df.empty or "DataHora" not in df.columns:
        return pd.Series(dtype=float)
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["DataHora"], errors="coerce")
    df = df.dropna(subset=["datetime"]).set_index("datetime").sort_index()
    col = "Vazao" if data_type == "flow" else "Nivel"
    if col not in df.columns:
        return pd.Series(dtype=float)
    vals = pd.to_numeric(df[col], errors="coerce")
    daily = vals.resample("D").mean().dropna()
    daily.index.name = "date"
    return daily


def data_type_of(code: str) -> str:
    """Le o tipo (flow/level) do baseline; default flow."""
    import json
    bl = Path(__file__).resolve().parent.parent / "data" / "baseline.json"
    if bl.exists():
        info = json.loads(bl.read_text(encoding="utf-8")).get(code, {})
        return info.get("data_type", "flow")
    return "flow"


def merge_current(code: str, new_daily: pd.Series) -> int:
    """Funde novos dias no buffer rolante. Retorna nro de dias novos."""
    if new_daily.empty:
        return 0
    path = CUR_DIR / f"{code}.parquet"
    if path.exists():
        old = pd.read_parquet(path)["value"]
        old.index = pd.to_datetime(old.index)
    else:
        old = pd.Series(dtype=float)
    added = new_daily.index.difference(old.index)
    merged = pd.concat([old, new_daily])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    cutoff = merged.index.max() - pd.Timedelta(days=KEEP_DAYS)
    merged = merged[merged.index >= cutoff]
    pd.DataFrame({"value": merged}).to_parquet(path)
    return len(added)


def main() -> None:
    today = datetime.utcnow().date()
    start = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    season_year = hydro.display_season_year(pd.Timestamp(today))

    print(f"Telemetria ANA | janela {start}..{end} | temporada {season_year}")
    print("=" * 60)

    ok, total_added = 0, 0
    for i, code in enumerate(STATIONS, 1):
        dtype = data_type_of(code)
        try:
            raw = fetch(code, start, end)
            daily = to_daily(raw, dtype)
            added = merge_current(code, daily)
            ok += 1
            total_added += added
            last = daily.index.max().date() if not daily.empty else "-"
            print(f"[{i:2d}/50] {code}  +{added:3d} dias (ultimo {last})")
        except Exception as e:  # noqa: BLE001
            print(f"[{i:2d}/50] {code}  ERRO: {e}")
        time.sleep(0.4)

    frac = ok / len(STATIONS)
    print("=" * 60)
    print(f"Sucesso: {ok}/50 ({frac:.0%}) | dias novos: {total_added}")
    if frac < MIN_SUCCESS_FRACTION:
        sys.exit(f"Taxa de sucesso {frac:.0%} < {MIN_SUCCESS_FRACTION:.0%} -- "
                 f"abortando para nao commitar dados incompletos")


if __name__ == "__main__":
    main()
