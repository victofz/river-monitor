"""
hydro.py -- logica hidrologica compartilhada (ETL + dashboard).

Conceito central: cada estacao e avaliada APENAS contra o seu proprio
historico. Nao ha benchmark externo nem parametros comerciais.

Indice: Cumulative Excess Index (CEI)
  Para o periodo de risco (1-out a 30-jun), soma dos excessos diarios
  acima do limiar P97 da propria estacao:
      CEI = sum( max(valor_dia - limiar_P97, 0) )
  O CEI da temporada corrente e comparado com a distribuicao dos CEIs
  das temporadas passadas da mesma estacao (rank percentil).
"""
from __future__ import annotations

import pandas as pd

# Periodo de risco: 1 de outubro a 30 de junho (273 dias)
SEASON_MONTHS = {10, 11, 12, 1, 2, 3, 4, 5, 6}
SEASON_LEN_DAYS = 273
THRESHOLD_PCT = 97  # limiar de excesso (percentil da propria estacao)


def display_season_year(today: pd.Timestamp) -> int:
    """Ano-base da temporada a exibir.

    Dentro da temporada (out-jun) => temporada ativa.
    Fora (jul-set) => ultima temporada encerrada.
    Ex.: qualquer dia de out/2026..jun/2027 -> 2026.
         jul..set/2026 -> 2025 (temporada que acabou de encerrar).
    """
    return today.year if today.month >= 10 else today.year - 1


def is_in_season(today: pd.Timestamp) -> bool:
    """True se hoje esta dentro do periodo de risco out-jun."""
    return today.month in SEASON_MONTHS


def season_bounds(season_year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(inicio, fim) da temporada: 1-out do ano-base a 30-jun do ano seguinte."""
    return pd.Timestamp(season_year, 10, 1), pd.Timestamp(season_year + 1, 6, 30)


def season_day(dates: pd.DatetimeIndex, season_year: int) -> pd.Index:
    """Dia da temporada (0 = 1-out) para um DatetimeIndex."""
    start, _ = season_bounds(season_year)
    return (dates.normalize() - start).days


def in_season(series: pd.Series) -> pd.Series:
    """Filtra uma serie diaria para os meses do periodo de risco."""
    return series[series.index.month.isin(SEASON_MONTHS)]


def season_slice(series: pd.Series, season_year: int) -> pd.Series:
    """Recorta a serie para uma temporada especifica (out-jun)."""
    start, end = season_bounds(season_year)
    return series[(series.index >= start) & (series.index <= end)]


def offseason_bounds(season_year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Janela de entressafra logo apos o fim da temporada (1-jul a 30-set)."""
    _, end = season_bounds(season_year)
    return end + pd.Timedelta(days=1), pd.Timestamp(season_year + 1, 9, 30)


def cei_curve(season_values: pd.Series, threshold: float) -> pd.Series:
    """Curva acumulada de excesso (CEI) ao longo da temporada.

    Retorna serie indexada pelo dia-da-temporada (0..272).
    """
    if season_values.empty:
        return pd.Series(dtype=float)
    excess = (season_values - threshold).clip(lower=0.0)
    # ano-base = o do inicio do recorte (1-out cai no ano-base)
    start = season_values.index.min()
    sy = start.year if start.month >= 10 else start.year - 1
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
