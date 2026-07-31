"""
Cálculo de stop e alvos da operação, baseado em ATR (Average True Range).

Abordagem padrão de gestão de risco por múltiplos de R (risco):
- Stop = 1.5x ATR de distância da entrada
- Alvo 1 = 1x o risco (relação 1:1)
- Alvo 2 = 2x o risco (relação 1:2)
- Alvo 3 = 3x o risco (relação 1:3)

Isso é uma referência ajustável — os multiplicadores podem virar
parâmetros de configuração no futuro, ou ser substituídos por uma lógica
mais sofisticada (ex.: baseada em estrutura de suporte/resistência).
"""

from core.entities import Lado, NiveisDeOperacao

MULTIPLICADOR_STOP_ATR = 1.5
MULTIPLICADORES_ALVOS = (1.0, 2.0, 3.0)


def calcular_niveis_operacao(preco_entrada: float, lado: Lado, atr: float | None) -> NiveisDeOperacao | None:
    if atr is None or atr <= 0:
        return None

    risco = atr * MULTIPLICADOR_STOP_ATR
    sinal = 1 if lado == Lado.COMPRA else -1

    stop = preco_entrada - sinal * risco
    alvo_1 = preco_entrada + sinal * risco * MULTIPLICADORES_ALVOS[0]
    alvo_2 = preco_entrada + sinal * risco * MULTIPLICADORES_ALVOS[1]
    alvo_3 = preco_entrada + sinal * risco * MULTIPLICADORES_ALVOS[2]

    return NiveisDeOperacao(
        stop=round(stop, 2),
        alvo_1=round(alvo_1, 2),
        alvo_2=round(alvo_2, 2),
        alvo_3=round(alvo_3, 2),
        risco_por_contrato=round(risco, 2),
        retorno_esperado_alvo_1=round(risco * MULTIPLICADORES_ALVOS[0], 2),
        relacao_risco_retorno=MULTIPLICADORES_ALVOS[0],  # relação do alvo 1, o mais conservador
    )
