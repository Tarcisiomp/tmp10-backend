"""
Orquestrador multi-ativo.

Roda um `SimuladorPaperTrading` independente para cada ativo configurado
(hoje: WIN e WDO), cada um com sua própria janela de horário e posição —
um ativo operando não afeta o outro. Isso é o que permite ao sistema
aproveitar dias em que um ativo não tem sinal de qualidade, mas o outro
tem (ver `docs/ESTUDO_HORARIOS.md` para o estudo que embasou os
parâmetros padrão abaixo).

Cada candle recebido é roteado para o simulador do ativo correspondente
pelo campo `candle.ativo` — então esse orquestrador pode receber candles
de vários ativos misturados (como aconteceria num feed ao vivo) e cada
um vai para o lugar certo.
"""

from dataclasses import dataclass, field
from datetime import time

from core.entities import Candle
from simulation.paper_trading import SimuladorPaperTrading


@dataclass
class ConfiguracaoAtivo:
    """Parâmetros específicos de um ativo, encontrados em `docs/ESTUDO_HORARIOS.md`."""

    ativo: str
    horario_limite_novas_operacoes: time
    quantidade_padrao: int = 1
    score_minimo_operacao: float = 60.0
    dias_permitidos: tuple[int, ...] | None = None  # None = usa o padrão (segunda a sexta)
    # Limites diários de segurança — escalados pro tamanho real de risco
    # de CADA ativo (o WDO vale R$10/ponto contra R$0,20 do WIN, então
    # os mesmos limites em R$ não fazem sentido pros dois — ver
    # market/instrumentos.py para o valor por ponto de cada um).
    stop_diario: float = 400.0
    meta_diaria: float = 600.0
    max_drawdown: float = 500.0
    limite_financeiro_diario: float = 1000.0
    max_operacoes_dia: int = 20  # cada ENTRADA gera 4 "operações" (1 por contrato) — isso permite ~5 entradas/dia


# Configuração padrão — resultado do estudo com dados reais de
# 13/02/2026 (WIN) e 13/04/2026 (WDO) a 28/07/2026. Ajustável conforme
# novos estudos ou preferência do operador (ver painel de configurações).
# Terça, quarta e sexta performaram consistentemente melhor que segunda
# e quinta no período estudado — ver docs/ESTUDO_HORARIOS.md.
#
# A saída (stop/alvos/trailing) NÃO é controlada aqui — isso é definido
# em orders/scale_out.py (CONFIGURACOES_SCALE_OUT), que o simulador usa
# automaticamente quando o ativo tem uma configuração validada.
CONFIGURACAO_PADRAO: list[ConfiguracaoAtivo] = [
    ConfiguracaoAtivo(
        ativo="WIN",
        horario_limite_novas_operacoes=time(10, 0),
        dias_permitidos=(1, 2, 4),
        stop_diario=400,        # ~3x o pior caso de 1 entrada perdedora (4 contratos x 150pts x R$0,20 = R$120)
        meta_diaria=600,
        max_drawdown=500,
        limite_financeiro_diario=1000,
    ),
    ConfiguracaoAtivo(
        ativo="WDO",
        horario_limite_novas_operacoes=time(12, 0),
        dias_permitidos=(1, 2, 4),
        stop_diario=3000,       # ~2,5x o pior caso de 1 entrada perdedora (4 contratos x 30pts x R$10 = R$1.200)
        meta_diaria=4000,
        max_drawdown=3500,
        limite_financeiro_diario=6000,
    ),
]


class OrquestradorMultiAtivo:
    def __init__(
        self,
        configuracoes: list[ConfiguracaoAtivo] | None = None,
        ao_decidir=None,
        ao_fechar_ordem=None,
        ao_abrir_ordem=None,
        configs_scale_out: dict | None = None,  # {"WIN": ConfiguracaoScaleOut, "WDO": ConfiguracaoScaleOut} — vindo do banco (ver database.repository.obter_configuracao_estrategia); None = usa os padrões validados
        custos_por_ativo: dict[str, float] | None = None,  # {"WIN": 0.62, "WDO": 3.10, ...} — Taxa Total por Contrato vinda de custos_operacionais (ver database.repository.obter_custo_vigente); None = custo 0 (nunca inventa um valor)
    ):
        self.configuracoes = configuracoes or CONFIGURACAO_PADRAO
        self.simuladores: dict[str, SimuladorPaperTrading] = {}
        configs_scale_out = configs_scale_out or {}

        for config in self.configuracoes:
            from orders.executor import ExecutorSimulado
            from risk.manager import GestorDeRiscoPadrao, LimitesDeRisco

            gestor_risco = GestorDeRiscoPadrao(
                LimitesDeRisco(
                    stop_por_operacao=config.stop_diario,  # não é mais usado pra sair da operação (isso é o scale-out) — só limita o pior caso de 1 operação isolada, se algum dia rodar sem scale-out
                    stop_diario=config.stop_diario,
                    meta_diaria=config.meta_diaria,
                    max_drawdown=config.max_drawdown,
                    max_operacoes_dia=config.max_operacoes_dia,
                    limite_financeiro_diario=config.limite_financeiro_diario,
                    score_minimo_operacao=config.score_minimo_operacao,
                    max_contratos=config.quantidade_padrao,
                )
            )

            self.simuladores[config.ativo] = SimuladorPaperTrading(
                ativo=config.ativo,
                gestor_risco=gestor_risco,
                quantidade_padrao=config.quantidade_padrao,
                horario_limite_novas_operacoes=config.horario_limite_novas_operacoes,
                dias_permitidos=config.dias_permitidos,
                ao_decidir=ao_decidir,
                ao_fechar_ordem=ao_fechar_ordem,
                ao_abrir_ordem=ao_abrir_ordem,
                config_scale_out=configs_scale_out.get(config.ativo),
                executor=ExecutorSimulado(custos_por_ativo=custos_por_ativo),
            )

    def processar_novo_candle(self, candle: Candle) -> None:
        """Roteia o candle para o simulador do ativo correspondente."""
        # Compara pelo prefixo, já que candles reais de contrato futuro
        # vêm com sufixo de vencimento (ex.: 'WINQ26' para o ativo 'WIN').
        for prefixo, simulador in self.simuladores.items():
            if candle.ativo.upper().startswith(prefixo.upper()):
                simulador.processar_novo_candle(candle)
                return

    def resultado_consolidado(self) -> dict:
        """Soma o resultado de todos os ativos, para uma visão geral do dia/período."""
        resultado_total = 0.0
        operacoes_total = 0
        por_ativo = {}

        for ativo, sim in self.simuladores.items():
            resultado_ativo = sim.resultado.resultado_financeiro_total
            operacoes_ativo = len(sim.resultado.ordens_fechadas)
            resultado_total += resultado_ativo
            operacoes_total += operacoes_ativo
            por_ativo[ativo] = {
                "resultado_financeiro_total": round(resultado_ativo, 2),
                "quantidade_operacoes": operacoes_ativo,
            }

        return {
            "resultado_financeiro_total": round(resultado_total, 2),
            "quantidade_operacoes_total": operacoes_total,
            "por_ativo": por_ativo,
        }
