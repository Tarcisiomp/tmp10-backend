"""
Motor de Backtest.

Reaproveita EXATAMENTE o mesmo pipeline do paper trading
(indicators -> ai -> risk -> orders), mas varrendo um histórico completo
de candles em vez de recebê-los "ao vivo". Ao final, calcula as métricas
pedidas: Win Rate, Profit Factor, Payoff, Drawdown, Lucro Líquido, Lucro
Bruto, Quantidade de operações, Médias de ganho/perda, Maiores sequências
de ganhos/perdas, Tempo médio das operações, Curva de capital e
Expectativa matemática.
"""

from dataclasses import dataclass, field

from core.entities import Candle, OrdemSimulada
from simulation.paper_trading import SimuladorPaperTrading


@dataclass
class MetricasBacktest:
    win_rate: float
    profit_factor: float
    payoff: float
    drawdown_maximo: float
    lucro_liquido: float  # em R$, já líquido do custo de B3 (emolumentos+liquidação) — ainda SEM o IR
    lucro_liquido_pontos: float  # o mesmo resultado, em pontos brutos, para conferência cruzada
    lucro_bruto: float
    custo_b3_total: float  # soma de todos os custos de bolsa pagos no período
    ir_estimado: float  # 20% sobre o lucro líquido do período, SE POSITIVO (day trade não paga IR sobre prejuízo)
    lucro_final_apos_ir: float  # o que realmente sobraria depois de bolsa + imposto — a resposta final
    quantidade_operacoes: int
    media_ganhos: float
    media_perdas: float
    maior_sequencia_ganhos: int
    maior_sequencia_perdas: int
    tempo_medio_operacao_minutos: float
    expectativa_matematica: float
    curva_capital: list[dict] = field(default_factory=list)


def _maior_sequencia(resultados: list[float], positivo: bool) -> int:
    maior = atual = 0
    for r in resultados:
        condicao = r > 0 if positivo else r < 0
        atual = atual + 1 if condicao else 0
        maior = max(maior, atual)
    return maior


def _tempo_medio_operacao_minutos(ordens: list[OrdemSimulada]) -> float:
    duracoes = [
        (o.timestamp_saida - o.timestamp_entrada).total_seconds() / 60
        for o in ordens
        if o.timestamp_saida is not None
    ]
    return round(sum(duracoes) / len(duracoes), 1) if duracoes else 0.0


def _calcular_metricas(ordens: list[OrdemSimulada], percentual_imposto: float = 20.0) -> MetricasBacktest:
    resultados = [o.resultado_financeiro for o in ordens if o.resultado_financeiro is not None]

    if not resultados:
        return MetricasBacktest(
            win_rate=0.0, profit_factor=0.0, payoff=0.0, drawdown_maximo=0.0,
            lucro_liquido=0.0, lucro_liquido_pontos=0.0, lucro_bruto=0.0,
            custo_b3_total=0.0, ir_estimado=0.0, lucro_final_apos_ir=0.0,
            quantidade_operacoes=0,
            media_ganhos=0.0, media_perdas=0.0, maior_sequencia_ganhos=0,
            maior_sequencia_perdas=0, tempo_medio_operacao_minutos=0.0,
            expectativa_matematica=0.0, curva_capital=[],
        )

    ganhos = [r for r in resultados if r > 0]
    perdas = [r for r in resultados if r < 0]

    win_rate = len(ganhos) / len(resultados) * 100
    soma_ganhos = sum(ganhos)
    soma_perdas = abs(sum(perdas))
    profit_factor = (soma_ganhos / soma_perdas) if soma_perdas > 0 else float("inf") if soma_ganhos > 0 else 0.0

    media_ganho = (soma_ganhos / len(ganhos)) if ganhos else 0.0
    media_perda = (soma_perdas / len(perdas)) if perdas else 0.0
    payoff = (media_ganho / media_perda) if media_perda > 0 else 0.0

    lucro_liquido = sum(resultados)
    lucro_liquido_pontos = sum(o.resultado_pontos for o in ordens if o.resultado_pontos is not None)
    lucro_bruto = soma_ganhos - soma_perdas  # bruto = soma dos ganhos - soma das perdas, sem outros custos ainda

    # Curva de capital + drawdown máximo
    curva_capital = []
    capital_acumulado = 0.0
    pico = 0.0
    drawdown_maximo = 0.0
    for i, ordem in enumerate(o for o in ordens if o.resultado_financeiro is not None):
        capital_acumulado += ordem.resultado_financeiro
        pico = max(pico, capital_acumulado)
        drawdown_atual = pico - capital_acumulado
        drawdown_maximo = max(drawdown_maximo, drawdown_atual)
        curva_capital.append(
            {
                "operacao": i + 1,
                "timestamp": ordem.timestamp_saida.isoformat() if ordem.timestamp_saida else None,
                "capital": round(capital_acumulado, 2),
            }
        )

    loss_rate = 1 - (len(ganhos) / len(resultados))
    expectativa_matematica = (len(ganhos) / len(resultados)) * media_ganho - loss_rate * media_perda

    ordens_fechadas = [o for o in ordens if o.resultado_financeiro is not None]
    custo_b3_total = sum(o.custo_b3 for o in ordens_fechadas if o.custo_b3 is not None)

    # IR de day trade: 20% sobre o RESULTADO LÍQUIDO do período, só se for
    # positivo (prejuízo não gera imposto a pagar — na prática a Receita
    # apura isso mês a mês, compensando perdas dentro do mesmo mês; aqui
    # tratamos o período inteiro do backtest como uma aproximação única).
    ir_estimado = round(max(0.0, lucro_liquido) * (percentual_imposto / 100), 2)
    lucro_final_apos_ir = round(lucro_liquido - ir_estimado, 2)

    return MetricasBacktest(
        win_rate=round(win_rate, 2),
        profit_factor=round(profit_factor, 2) if profit_factor != float("inf") else profit_factor,
        payoff=round(payoff, 2),
        drawdown_maximo=round(drawdown_maximo, 2),
        lucro_liquido=round(lucro_liquido, 2),
        lucro_liquido_pontos=round(lucro_liquido_pontos, 2),
        lucro_bruto=round(lucro_bruto, 2),
        custo_b3_total=round(custo_b3_total, 2),
        ir_estimado=ir_estimado,
        lucro_final_apos_ir=lucro_final_apos_ir,
        quantidade_operacoes=len(resultados),
        media_ganhos=round(media_ganho, 2),
        media_perdas=round(media_perda, 2),
        maior_sequencia_ganhos=_maior_sequencia(resultados, positivo=True),
        maior_sequencia_perdas=_maior_sequencia(resultados, positivo=False),
        tempo_medio_operacao_minutos=_tempo_medio_operacao_minutos(ordens_fechadas),
        expectativa_matematica=round(expectativa_matematica, 2),
        curva_capital=curva_capital,
    )


def rodar_backtest(
    ativo: str,
    candles_historico: list[Candle],
    janela_indicadores: int = 100,
    quantidade_padrao: int = 1,
    executor=None,  # ExecutorDeOrdens opcional — passe um ExecutorSimulado(custos_por_ativo={...}) pra descontar custos reais (ver database.repository.obter_custo_vigente)
    percentual_imposto: float = 20.0,  # % de IR sobre o resultado do período — busque em database.repository.obter_configuracao_financeira pra não ficar fixo
    **horario_kwargs,
) -> MetricasBacktest:
    """
    Varre `candles_historico` (do mais antigo para o mais recente)
    alimentando o SimuladorPaperTrading candle a candle, e ao final
    calcula as métricas de performance.

    `**horario_kwargs` repassa parâmetros de janela de horário (ex.:
    `horario_limite_novas_operacoes=time(10, 0)`) direto para o
    SimuladorPaperTrading, útil para testar restringir o sistema a
    operar só em determinada faixa do pregão.
    """
    simulador = SimuladorPaperTrading(
        ativo=ativo,
        janela_indicadores=janela_indicadores,
        quantidade_padrao=quantidade_padrao,
        executor=executor,
        **horario_kwargs,
    )

    for candle in candles_historico:
        simulador.processar_novo_candle(candle)

    return _calcular_metricas(simulador.resultado.ordens_fechadas, percentual_imposto)


def rodar_backtest_multi_ativo(
    candles_por_ativo: dict[str, list[Candle]],
    configuracoes: list | None = None,
) -> dict:
    """
    Roda o backtest para vários ativos ao mesmo tempo, cada um com sua
    própria janela de horário (ver `simulation/orquestrador.py` e
    `docs/ESTUDO_HORARIOS.md`), e devolve as métricas de cada ativo mais
    o resultado combinado.

    `candles_por_ativo`: ex.: {"WIN": candles_win_15m, "WDO": candles_wdo_15m}
    """
    from simulation.orquestrador import OrquestradorMultiAtivo

    orquestrador = OrquestradorMultiAtivo(configuracoes=configuracoes)

    # Mescla todos os candles em ordem cronológica, como aconteceria
    # recebendo um feed ao vivo com vários ativos misturados.
    todos_os_candles = sorted(
        (c for candles in candles_por_ativo.values() for c in candles),
        key=lambda c: c.timestamp,
    )

    for candle in todos_os_candles:
        orquestrador.processar_novo_candle(candle)

    resultado_por_ativo = {}
    for ativo, sim in orquestrador.simuladores.items():
        resultado_por_ativo[ativo] = _calcular_metricas(sim.resultado.ordens_fechadas, percentual_imposto)

    lucro_liquido_total = sum(m.lucro_liquido for m in resultado_por_ativo.values())
    lucro_final_total = sum(m.lucro_final_apos_ir for m in resultado_por_ativo.values())
    operacoes_total = sum(m.quantidade_operacoes for m in resultado_por_ativo.values())

    return {
        "por_ativo": resultado_por_ativo,
        "combinado": {
            "quantidade_operacoes": operacoes_total,
            "lucro_liquido_total": round(lucro_liquido_total, 2),
            "lucro_final_apos_ir_total": round(lucro_final_total, 2),
        },
    }
