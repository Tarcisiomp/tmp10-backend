"""
Motor de cálculo financeiro.

Ponto-chave da arquitetura: os trades guardam o resultado em PONTOS
(fato imutável — não muda nunca). Tudo em R$ (custos, impostos, lucro
líquido) é calculado AQUI, em cima da configuração ATUAL — então, se o
usuário mudar uma taxa hoje, todo relatório (mesmo de operações de
meses atrás) recalcula automaticamente com o valor novo, sem precisar
reprocessar nem alterar nada no banco.
"""

from dataclasses import dataclass, field
from datetime import datetime

from database.models import TradeModel
from market.instrumentos import obter_valor_por_ponto


@dataclass
class ResultadoOperacaoFinanceiro:
    trade_id: int
    ativo: str
    timestamp_entrada: datetime
    timestamp_saida: datetime | None
    quantidade: int
    resultado_pontos: float
    lucro_bruto: float
    custos: float
    lucro_liquido: float


@dataclass
class ResumoFinanceiro:
    lucro_bruto: float = 0.0
    prejuizo_bruto: float = 0.0
    lucro_liquido: float = 0.0
    total_operacoes: int = 0
    operacoes_vencedoras: int = 0
    operacoes_perdedoras: int = 0
    taxa_acerto: float = 0.0
    profit_factor: float = 0.0
    drawdown_maximo: float = 0.0
    media_gain: float = 0.0
    media_loss: float = 0.0
    total_taxas_pagas: float = 0.0
    imposto_estimado: float = 0.0
    lucro_disponivel: float = 0.0
    maior_gain: float = 0.0
    maior_loss: float = 0.0


def calcular_custos_operacao(ativo: str, quantidade: int, custos_por_ativo: dict[str, float]) -> float:
    """
    Custos de UMA operação completa. A Taxa Total por Contrato vem de
    `custos_por_ativo` — SEMPRE buscada em custos_operacionais (ver
    database.repository.obter_custo_vigente), nunca um valor fixo
    escrito aqui. Se o ativo não tiver custo cadastrado, o custo é 0
    (nunca inventa um número).
    """
    taxa_total_contrato = custos_por_ativo.get(ativo.upper(), 0.0)
    return taxa_total_contrato * quantidade


def calcular_resultado_operacao(
    trade: TradeModel, config: dict, custos_por_ativo: dict[str, float]
) -> ResultadoOperacaoFinanceiro:
    valor_por_ponto = obter_valor_por_ponto(trade.ativo)
    pontos = trade.resultado_pontos or 0.0
    lucro_bruto = pontos * valor_por_ponto * trade.quantidade
    custos = calcular_custos_operacao(trade.ativo, trade.quantidade, custos_por_ativo)
    lucro_liquido = lucro_bruto - custos

    return ResultadoOperacaoFinanceiro(
        trade_id=trade.id,
        ativo=trade.ativo,
        timestamp_entrada=trade.timestamp_entrada,
        timestamp_saida=trade.timestamp_saida,
        quantidade=trade.quantidade,
        resultado_pontos=pontos,
        lucro_bruto=round(lucro_bruto, 2),
        custos=round(custos, 2),
        lucro_liquido=round(lucro_liquido, 2),
    )


def calcular_resumo(
    trades: list[TradeModel], config: dict, custos_por_ativo: dict[str, float]
) -> ResumoFinanceiro:
    """Calcula o painel financeiro completo a partir de uma lista de trades FECHADOS."""
    resultados = [
        calcular_resultado_operacao(t, config, custos_por_ativo) for t in trades if t.resultado_pontos is not None
    ]

    if not resultados:
        return ResumoFinanceiro()

    lucros_liquidos = [r.lucro_liquido for r in resultados]
    ganhos = [v for v in lucros_liquidos if v > 0]
    perdas = [v for v in lucros_liquidos if v <= 0]

    lucro_bruto_total = sum(r.lucro_bruto for r in resultados if r.lucro_bruto > 0)
    prejuizo_bruto_total = sum(r.lucro_bruto for r in resultados if r.lucro_bruto < 0)
    total_taxas = sum(r.custos for r in resultados)
    lucro_liquido_total = sum(lucros_liquidos)

    soma_ganhos = sum(ganhos)
    soma_perdas = abs(sum(perdas))
    profit_factor = round(soma_ganhos / soma_perdas, 2) if soma_perdas > 0 else (float("inf") if soma_ganhos > 0 else 0.0)

    # drawdown máximo sobre a curva de capital acumulada (ordenado por saída)
    resultados_ordenados = sorted(resultados, key=lambda r: r.timestamp_saida or r.timestamp_entrada)
    acumulado = 0.0
    pico = 0.0
    drawdown_maximo = 0.0
    for r in resultados_ordenados:
        acumulado += r.lucro_liquido
        pico = max(pico, acumulado)
        drawdown_maximo = max(drawdown_maximo, pico - acumulado)

    imposto_estimado = round(max(0.0, lucro_liquido_total) * (config["percentual_imposto"] / 100), 2)

    return ResumoFinanceiro(
        lucro_bruto=round(lucro_bruto_total, 2),
        prejuizo_bruto=round(prejuizo_bruto_total, 2),
        lucro_liquido=round(lucro_liquido_total, 2),
        total_operacoes=len(resultados),
        operacoes_vencedoras=len(ganhos),
        operacoes_perdedoras=len(perdas),
        taxa_acerto=round(len(ganhos) / len(resultados) * 100, 2) if resultados else 0.0,
        profit_factor=profit_factor,
        drawdown_maximo=round(drawdown_maximo, 2),
        media_gain=round(soma_ganhos / len(ganhos), 2) if ganhos else 0.0,
        media_loss=round(sum(perdas) / len(perdas), 2) if perdas else 0.0,
        total_taxas_pagas=round(total_taxas, 2),
        imposto_estimado=imposto_estimado,
        lucro_disponivel=round(lucro_liquido_total - imposto_estimado, 2),
        maior_gain=round(max(lucros_liquidos), 2) if lucros_liquidos else 0.0,
        maior_loss=round(min(lucros_liquidos), 2) if lucros_liquidos else 0.0,
    )
