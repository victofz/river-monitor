"""
Painel de estacoes telemetricas ANA monitoradas (Rio Grande do Sul).

50 estacoes com telemetria em tempo real (transmissao ~15 min via SOAP da ANA)
e historico longo o suficiente para comparacoes estatisticas robustas.
"""

# Codigos ANA (codigoestacao). Cada estacao e comparada apenas com o
# proprio historico -- nao ha panel "comercial", apenas monitoramento.
STATIONS = [
    "70840080", "73390000", "73420080", "74040080", "74100000", "74500000",
    "74800000", "75230000", "75290000", "75500000", "75550000", "75780000",
    "75900000", "76251000", "76300000", "76310000", "76560000", "76700000",
    "76742000", "76750000", "76800000", "77150000", "77500000", "79400000",
    "85400000", "85642000", "85900000", "86160000", "86305000", "86448000",
    "86470800", "86500000", "86510000", "86560000", "86720000", "86881000",
    "86895000", "86950000", "87020000", "87160000", "87170000", "87270000",
    "87300000", "87317030", "87380000", "87382000", "87399000", "87450100",
    "87905000", "88260000",
]
