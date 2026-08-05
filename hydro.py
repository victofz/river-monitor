"""
hydro.py -- logica hidrologica compartilhada (ETL + dashboard).

Conceito central: cada estacao e avaliada APENAS contra o seu proprio
historico. Nao ha benchmark externo nem parametros comerciais.

Temporada: ciclo continuo de 12 meses, 1-jul a 30-jun do ano seguinte.
Jul-set (antiga "entressafra") e tratado como o INICIO da temporada, nao
como um intervalo separado entre temporadas -- nao ha mais congelamento
nem gap: o indice acumula o ano inteiro, sem interrupcao.

Indice: Cumulative Excess Index (CEI)
  Soma dos excessos diarios acima do limiar P97 da propria estacao,
  ao longo da temporada:
      CEI = sum( max(valor_dia - limiar_P97, 0) )
  O CEI da temporada corrente e comparado com a distribuicao dos CEIs
  das temporadas passadas da mesma estacao (rank percentil).
"""
from __future__ import annotations

import pandas as pd

SEASON_LEN_DAYS = 366  # 1-jul a 30-jun, com folga p/ ano bissexto
THRESHOLD_PCT = 97     # limiar de excesso (percentil da propria estacao)


def display_season_year(today: pd.Timestamp) -> int:
    """Ano-base da temporada a exibir (1-jul do ano-base a 30-jun do seguinte)."""
    return today.year if today.month >= 7 else today.year - 1


def season_bounds(season_year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(inicio, fim) da temporada: 1-jul do ano-base a 30-jun do ano seguinte."""
    return pd.Timestamp(season_year, 7, 1), pd.Timestamp(season_year + 1, 6, 30)


def season_day(dates: pd.DatetimeIndex, season_year: int) -> pd.Index:
    """Dia da temporada (0 = 1-jul) para um DatetimeIndex."""
    start, _ = season_bounds(season_year)
    return (dates.normalize() - start).days


def season_slice(series: pd.Series, season_year: int) -> pd.Series:
    """Recorta a serie para uma temporada especifica (1-jul a 30-jun)."""
    start, end = season_bounds(season_year)
    return series[(series.index >= start) & (series.index <= end)]


def cei_curve(season_values: pd.Series, threshold: float) -> pd.Series:
    """Curva acumulada de excesso (CEI) ao longo da temporada.

    Retorna serie indexada pelo dia-da-temporada (0 = 1-jul).
    """
    if season_values.empty:
        return pd.Series(dtype=float)
    excess = (season_values - threshold).clip(lower=0.0)
    start = season_values.index.min()
    sy = start.year if start.month >= 7 else start.year - 1
    days = season_day(excess.index, sy)
    cum = excess.cumsum()
    cum.index = days
    return cum[(cum.index >= 0) & (cum.index < SEASON_LEN_DAYS)]


def daily_status(value: float, p90: float, p97: float, p99: float) -> str:
    """Classifica um valor diario contra os percentis da propria estacao."""
    if value is None or pd.isna(value):
        return "sem_dado"
    if value >= p99:
        return "extremo"
    if value >= p97:
        return "alto"
    if value >= p90:
        return "elevado"
    return "normal"


STATUS_COLORS = {
    "normal": "#2E86AB",   # azul
    "elevado": "#F6C453",  # amarelo
    "alto": "#E8871E",     # laranja
    "extremo": "#D7263D",  # vermelho
    "sem_dado": "#9AA0A6", # cinza
}

STATUS_LABEL = {
    "normal": "Normal",
    "elevado": "Elevado (>P90)",
    "alto": "Alto (>P97)",
    "extremo": "Extremo (>P99)",
    "sem_dado": "Sem dado",
}
