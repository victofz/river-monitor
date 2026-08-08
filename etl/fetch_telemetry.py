"""
fetch_telemetry.py -- busca telemetria em tempo real da ANA (roda de hora em hora).

Baixa as leituras sub-diarias (~15 min) das 50 estacoes via SOAP, agrega
para media diaria e atualiza data/current/<code>.parquet -- um buffer
rolante (ultimos KEEP_DAYS dias) com colunas "flow" e/ou "level" (o que
a estacao transmitir), NAO recortado por temporada. O recorte 1-jul a
30-jun (para o CEI) e feito na leitura, em build_index.py e app.py.

Robusto por design:
  - cada estacao e buscada e fundida de forma isolada (try/except) -- uma
    falha numa estacao nunca corrompe as outras, so aquela fica sem o dado
    novo desta rodada (o buffer que ja existia continua intacto);
  - por isso o job SEMPRE termina com sucesso (exit 0), mesmo com varias
    estacoes falhando -- a API da ANA e publica e ocasionalmente instavel,
    e isso nao deveria gerar alerta de falha por e-mail a cada rodada.
"""
from __future__ import annotations

import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from stations import STATIONS  # noqa: E402

SOAP_URL = "http://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
XML_TAG = "DadosHidrometereologicos"  # typo original da ANA -- manter

CUR_DIR = Path(__file__).resolve().parent.parent / "data" / "current"
CUR_DIR.mkdir(parents=True, exist_ok=True)

LOOKBACK_DAYS = 45          # janela buscada a cada rodada
KEEP_DAYS = 450              # buffer rolante guardado no parquet (~15 meses)
MIN_SUCCESS_WARN = 0.5       # abaixo disto, so um aviso no log (nao falha o job)
RETRIES = 2                  # tentativas extras por estacao antes de desistir
RETRY_WAIT = 4                # segundos entre tentativas


def fetch(code: str, start: str, end: str) -> pd.DataFrame:
    params = {"codEstacao": code, "dataInicio": start, "dataFim": end}
    last_err = None
    for attempt in range(RETRIES + 1):
        try:
            r = requests.get(SOAP_URL, params=params, timeout=120)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            rows = []
            for rec in root.iter(XML_TAG):
                rows.append({c.tag.split("}")[-1]: c.text for c in rec})
            return pd.DataFrame(rows)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < RETRIES:
                time.sleep(RETRY_WAIT)
    raise last_err


def to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega telemetria bruta para serie diaria (media), colunas flow/level
    -- as duas que existirem na resposta."""
    if df.empty or "DataHora" not in df.columns:
        return pd.DataFrame()
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["DataHora"], errors="coerce")
    df = df.dropna(subset=["datetime"]).set_index("datetime").sort_index()

    cols = {}
    if "Vazao" in df.columns:
        vals = pd.to_numeric(df["Vazao"], errors="coerce")
        daily = vals.resample("D").mean().dropna()
        if not daily.empty:
            cols["flow"] = daily
    if "Nivel" in df.columns:
        vals = pd.to_numeric(df["Nivel"], errors="coerce")
        daily = vals.resample("D").mean().dropna()
        if not daily.empty:
            cols["level"] = daily

    if not cols:
        return pd.DataFrame()
    out = pd.DataFrame(cols)
    out.index.name = "date"
    return out


def merge_current(code: str, new_daily: pd.DataFrame) -> int:
    """Funde novos dias no buffer rolante (colunas flow/level). Retorna
    numero de linhas novas (dias com pelo menos uma leitura nova)."""
    if new_daily.empty:
        return 0
    path = CUR_DIR / f"{code}.parquet"
    if path.exists():
        old = pd.read_parquet(path)
        old.index = pd.to_datetime(old.index)
    else:
        old = pd.DataFrame()

    added = new_daily.index.difference(old.index) if not old.empty else new_daily.index
    all_cols = sorted(set(old.columns) | set(new_daily.columns))
    old = old.reindex(columns=all_cols)
    new_daily = new_daily.reindex(columns=all_cols)

    merged = pd.concat([old, new_daily])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    cutoff = merged.index.max() - pd.Timedelta(days=KEEP_DAYS)
    merged = merged[merged.index >= cutoff]
    merged.to_parquet(path)
    return len(added)


def main() -> None:
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    print(f"Telemetria ANA | janela {start}..{end}")
    print("=" * 60)

    ok, total_added = 0, 0
    for i, code in enumerate(STATIONS, 1):
        try:
            raw = fetch(code, start, end)
            daily = to_daily(raw)
            added = merge_current(code, daily)
            ok += 1
            total_added += added
            cols = "+".join(daily.columns) if not daily.empty else "-"
            last = daily.index.max().date() if not daily.empty else "-"
            print(f"[{i:2d}/50] {code}  +{added:3d} dias [{cols}] (ultimo {last})")
        except Exception as e:  # noqa: BLE001
            print(f"[{i:2d}/50] {code}  ERRO: {e}")
        time.sleep(0.4)

    frac = ok / len(STATIONS)
    print("=" * 60)
    print(f"Sucesso: {ok}/50 ({frac:.0%}) | dias novos: {total_added}")
    if frac < MIN_SUCCESS_WARN:
        print(f"AVISO: taxa de sucesso {frac:.0%} abaixo do esperado -- "
              f"provavelmente instabilidade pontual da API da ANA. As estacoes "
              f"que falharam mantem o dado que ja tinham; sem risco de corrupcao.")
    # sempre exit 0: uma rodada ruim nao deve gerar alerta de falha por e-mail


if __name__ == "__main__":
    main()
