"""
Gestão de Risco — módulo completamente independente do motor de decisão.

O motor de decisão pode mandar "COMPRAR" o quanto quiser: quem decide se
a ordem realmente pode ser aberta é este módulo. Isso é proposital —
separar "o que a IA acha que deveria fazer" de "o que é seguro fazer
agora", conforme pedido explicitamente no projeto original.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from core.entities import OrdemSimulada
from core.interfaces import GestorDeRisco
from market.pregao import obter_status_pregao


@dataclass
class LimitesDeRisco:
    stop_por_operacao: float
    stop_diario: float
    meta_diaria: float
    max_drawdown: float
    max_operacoes_dia: int
    limite_financeiro_diario: float
    score_minimo_operacao: float = 70.0  # Score da IA (0-100) mínimo para abrir uma operação nova
    max_contratos: int = 1  # quantidade máxima de contratos por operação


@dataclass
class EstadoDeRiscoDiario:
    data: date
    resultado_do_dia: float = 0.0
    pico_de_capital_do_dia: float = 0.0
    operacoes_realizadas: int = 0
    bloqueado: bool = False
    motivo_bloqueio: str = ""
    historico_resultados: list[float] = field(default_factory=list)


class GestorDeRiscoPadrao(GestorDeRisco):
    def __init__(self, limites: LimitesDeRisco):
        self.limites = limites
        self.estado = EstadoDeRiscoDiario(data=datetime.utcnow().date())

    def _resetar_se_novo_dia(self, agora=None) -> None:
        hoje = (agora or datetime.utcnow()).date()
        if hoje != self.estado.data:
            self.estado = EstadoDeRiscoDiario(data=hoje)

    def pode_operar(self, agora=None, score_ia: float | None = None) -> tuple[bool, str]:
        self._resetar_se_novo_dia(agora)

        # Horário de pregão tem prioridade sobre qualquer outra regra:
        # fora do horário (ou perto do fechamento), não abre operação nova,
        # independentemente do estado de bloqueio interno.
        status_pregao = obter_status_pregao(agora)
        if not status_pregao.aceita_novas_operacoes:
            return False, status_pregao.motivo

        # Score da IA: só opera se o Score atingir o mínimo configurado.
        if score_ia is not None and score_ia < self.limites.score_minimo_operacao:
            return False, (
                f"Score da IA ({score_ia:.0f}/100) abaixo do mínimo exigido "
                f"({self.limites.score_minimo_operacao:.0f}/100) para operar"
            )

        if self.estado.bloqueado:
            return False, self.estado.motivo_bloqueio

        if self.estado.operacoes_realizadas >= self.limites.max_operacoes_dia:
            self._bloquear("Número máximo de operações do dia atingido")
            return False, self.estado.motivo_bloqueio

        if self.estado.resultado_do_dia <= -self.limites.stop_diario:
            self._bloquear("Stop diário atingido")
            return False, self.estado.motivo_bloqueio

        if self.estado.resultado_do_dia >= self.limites.meta_diaria:
            self._bloquear("Meta diária atingida — operações encerradas por segurança")
            return False, self.estado.motivo_bloqueio

        drawdown_atual = self.estado.pico_de_capital_do_dia - self.estado.resultado_do_dia
        if drawdown_atual >= self.limites.max_drawdown:
            self._bloquear("Limite máximo de drawdown do dia atingido")
            return False, self.estado.motivo_bloqueio

        if abs(self.estado.resultado_do_dia) >= self.limites.limite_financeiro_diario:
            self._bloquear("Limite financeiro diário atingido")
            return False, self.estado.motivo_bloqueio

        return True, ""

    def registrar_resultado(self, ordem: OrdemSimulada, agora=None) -> None:
        self._resetar_se_novo_dia(agora or ordem.timestamp_saida)

        if ordem.resultado_financeiro is None:
            return

        self.estado.operacoes_realizadas += 1
        self.estado.resultado_do_dia += ordem.resultado_financeiro
        self.estado.historico_resultados.append(ordem.resultado_financeiro)
        self.estado.pico_de_capital_do_dia = max(
            self.estado.pico_de_capital_do_dia, self.estado.resultado_do_dia
        )

        # Stop por operação: se uma única operação perdeu mais que o limite,
        # bloqueia imediatamente (independentemente do saldo do dia).
        if ordem.resultado_financeiro <= -self.limites.stop_por_operacao:
            self._bloquear(
                f"Stop por operação atingido em uma única operação "
                f"(perda de {ordem.resultado_financeiro:.2f})"
            )

    def _bloquear(self, motivo: str) -> None:
        self.estado.bloqueado = True
        self.estado.motivo_bloqueio = motivo

    def desbloquear_manualmente(self) -> None:
        """Permite ao operador humano destravar o sistema manualmente (ex.: no dashboard)."""
        self.estado.bloqueado = False
        self.estado.motivo_bloqueio = ""
