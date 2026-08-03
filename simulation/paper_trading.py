"""
Simulador de Paper Trading.

Orquestra o fluxo completo (indicators → ai → risk → orders) usando
dados simulados/em tempo (quase) real, sem enviar nenhuma ordem real.
Registra entrada, saída, lucro/prejuízo, tempo da operação e motivos, e
mantém a última decisão/semáforo disponíveis para o painel consultar o
que a IA está "pensando" agora — não só o histórico já fechado.
"""

import numpy as np
from dataclasses import dataclass, field

from ai.classifiers.market import ClassificadorDeVolatilidadeHeuristico
from ai.decision.engine import MotorDeDecisaoHeuristico
from ai.patterns.recognizer import ReconhecedorDePadroesHeuristico
from ai.reversal.detector import DetectorDeReversaoHeuristico
from ai.trend.detector import DetectorDeTendenciaHeuristico
from core.entities import Candle, ContextoMercado, Decisao, DecisaoTrade, Lado, OrdemSimulada
from core.interfaces import ExecutorDeOrdens, GestorDeRisco, MotorDeDecisao
from indicators.technical import calcular_snapshot
from market.pregao import StatusPregao, obter_status_pregao
from market.semaforo import ItemSemaforo, calcular_semaforo
from orders.executor import ExecutorSimulado
from orders.scale_out import calcular_stop_atual_pontos, obter_configuracao_scale_out, preco_do_alvo, preco_do_stop
from risk.manager import GestorDeRiscoPadrao, LimitesDeRisco

JANELA_VOLUME_MEDIO = 20


@dataclass
class ResultadoSimulacao:
    ordens_fechadas: list[OrdemSimulada] = field(default_factory=list)
    ordens_abertas: list[OrdemSimulada] = field(default_factory=list)
    resultado_financeiro_total: float = 0.0

    @property
    def ordem_aberta(self) -> OrdemSimulada | None:
        """Compatibilidade: devolve a 1ª ordem aberta, se houver (uso legado, 1 ordem por vez)."""
        return self.ordens_abertas[0] if self.ordens_abertas else None


class SimuladorPaperTrading:
    """
    Mantém um buffer de candles e, a cada novo candle recebido, roda o
    pipeline completo: calcula indicadores -> classifica tendência,
    reversão, padrões e volatilidade -> pede a decisão ao motor -> valida
    com a gestão de risco (incluindo o Score mínimo da IA) -> executa
    (simulado) -> registra o resultado.

    Após cada candle processado, `ultima_decisao`, `ultimo_semaforo` e
    `ultimo_status_pregao` ficam disponíveis para consulta — é o que
    alimenta o painel em tempo (quase) real, sem depender apenas do
    histórico já persistido no banco.
    """

    def __init__(
        self,
        ativo: str,
        motor_decisao: MotorDeDecisao | None = None,
        gestor_risco: GestorDeRisco | None = None,
        executor: ExecutorDeOrdens | None = None,
        janela_indicadores: int = 100,
        quantidade_padrao: int = 1,
        ao_decidir=None,  # callback opcional: (DecisaoTrade) -> None — usado para persistir no banco
        ao_fechar_ordem=None,  # callback opcional: (OrdemSimulada) -> None
        ao_abrir_ordem=None,  # callback opcional: (OrdemSimulada) -> None — chamado ao ABRIR (útil pra persistir posições em scale-out antes delas fecharem)
        horario_abertura=None,
        horario_fechamento=None,
        horario_limite_novas_operacoes=None,
        horario_fechamento_forcado=None,
        dias_permitidos=None,
        config_scale_out=None,  # ConfiguracaoScaleOut opcional — sobrescreve a config padrão do ativo (ver orders/scale_out.py)
    ):
        self.ativo = ativo
        self._config_scale_out_override = config_scale_out
        self.motor_decisao = motor_decisao or MotorDeDecisaoHeuristico()
        self.gestor_risco = gestor_risco or GestorDeRiscoPadrao(
            LimitesDeRisco(
                stop_por_operacao=100,      # R$100 = 500 pontos de WIN por operação
                stop_diario=300,            # R$300 = 1.500 pontos de perda acumulada no dia
                meta_diaria=400,            # R$400 = 2.000 pontos de ganho acumulado no dia
                max_drawdown=400,
                max_operacoes_dia=10,
                limite_financeiro_diario=600,
                score_minimo_operacao=70,
            )
        )
        self.executor = executor or ExecutorSimulado()

        self.detector_tendencia = DetectorDeTendenciaHeuristico()
        self.detector_reversao = DetectorDeReversaoHeuristico()
        self.reconhecedor_padroes = ReconhecedorDePadroesHeuristico()
        self.classificador_volatilidade = ClassificadorDeVolatilidadeHeuristico()

        self.janela_indicadores = janela_indicadores
        self.quantidade_padrao = quantidade_padrao
        self._ao_decidir = ao_decidir
        self._ao_fechar_ordem = ao_fechar_ordem
        self._ao_abrir_ordem = ao_abrir_ordem

        # Janela de horário configurável — permite, por exemplo, restringir
        # o sistema a operar só na primeira hora do pregão, se um estudo
        # (como o feito em docs/ESTUDO_HORARIOS.md) mostrar que é ali que
        # está a vantagem estatística real.
        self._horario_kwargs = {
            k: v
            for k, v in {
                "horario_abertura": horario_abertura,
                "horario_fechamento": horario_fechamento,
                "horario_limite_novas_operacoes": horario_limite_novas_operacoes,
                "horario_fechamento_forcado": horario_fechamento_forcado,
                "dias_permitidos": dias_permitidos,
            }.items()
            if v is not None
        }

        self._buffer: list[Candle] = []
        self.resultado = ResultadoSimulacao()

        self.ultima_decisao: DecisaoTrade | None = None
        self.ultimo_semaforo: list[ItemSemaforo] = []
        self.ultimo_status_pregao: StatusPregao | None = None

    def _volume_relativo(self, janela: list[Candle]) -> float | None:
        if len(janela) < 2:
            return None
        historico = janela[:-1][-JANELA_VOLUME_MEDIO:]
        if not historico:
            return None
        media = float(np.mean([c.volume for c in historico]))
        if media == 0:
            return None
        return janela[-1].volume / media

    def processar_novo_candle(self, candle: Candle) -> None:
        self._buffer.append(candle)
        janela = self._buffer[-self.janela_indicadores :]

        indicadores = calcular_snapshot(janela)
        tendencia = self.detector_tendencia.classificar(janela, indicadores)
        reversao = self.detector_reversao.detectar(janela, indicadores)
        padroes = self.reconhecedor_padroes.reconhecer(janela)
        volatilidade = self.classificador_volatilidade.classificar(janela, indicadores)
        volume_relativo = self._volume_relativo(janela)

        contexto = ContextoMercado(
            ativo=self.ativo,
            timeframe=candle.timeframe,
            candle_atual=candle,
            indicadores=indicadores,
            tendencia=tendencia,
            reversao_detectada=reversao,
            padroes_detectados=padroes,
            classe_volatilidade=volatilidade,
            volume_relativo=volume_relativo,
            horario=candle.timestamp,
        )

        status_pregao = obter_status_pregao(candle.timestamp, **self._horario_kwargs)
        self.ultimo_status_pregao = status_pregao
        self.ultimo_semaforo = calcular_semaforo(contexto, status_pregao)

        config_scale_out = self._config_scale_out_override or obter_configuracao_scale_out(self.ativo)

        # Fechamento forçado de segurança perto do encerramento do pregão,
        # independentemente do que o motor de decisão sinalizar.
        if self.resultado.ordens_abertas and status_pregao.deve_fechar_posicoes_abertas:
            for ordem in list(self.resultado.ordens_abertas):
                ordem_fechada = self.executor.fechar_ordem(
                    ordem,
                    preco_saida=candle.fechamento,
                    motivo_saida=f"Fechamento automático por horário de pregão: {status_pregao.motivo}",
                    timestamp_saida=candle.timestamp,
                )
                self._registrar_fechamento(ordem_fechada)
            self.resultado.ordens_abertas = []
            return

        ha_operacao_aberta = bool(self.resultado.ordens_abertas)

        if ha_operacao_aberta:
            if config_scale_out is not None:
                # Gestão por stop/alvos fixos (a estratégia validada com
                # dado real) — não depende do motor de decisão pra sair.
                self._gerenciar_scale_out(candle, config_scale_out)
                # Ainda assim, atualiza a "última decisão" pro painel
                # mostrar o que a IA está vendo agora, mesmo em posição.
                decisao = self.motor_decisao.decidir(contexto, risco_aprovado=True, ha_operacao_aberta=True)
                self._notificar_decisao(decisao)
            else:
                # Comportamento legado: fecha quando o motor sinaliza o
                # lado oposto (usado para ativos sem configuração de
                # scale-out validada).
                decisao = self.motor_decisao.decidir(contexto, risco_aprovado=True, ha_operacao_aberta=True)
                self._notificar_decisao(decisao)
                self._avaliar_fechamento_legado(contexto, decisao)
            return

        # Se a janela de horário (a mesma usada acima, já com eventual
        # configuração customizada) não aceita novas operações, para por
        # aqui — sem isso, o gestor de risco recalcularia o horário por
        # conta própria, com os parâmetros padrão, ignorando qualquer
        # janela customizada passada ao simulador.
        if not status_pregao.aceita_novas_operacoes:
            return

        # 1ª passada: calcula a decisão assumindo risco aprovado, só para
        # obter o Score da IA (o gate de risco real depende desse score).
        decisao_preliminar = self.motor_decisao.decidir(contexto, risco_aprovado=True, ha_operacao_aberta=False)

        pode_operar, motivo_bloqueio = self.gestor_risco.pode_operar(candle.timestamp, decisao_preliminar.score_ia)

        # 2ª passada: recalcula com o resultado real do risco, para que o
        # checklist e a explicação reflitam o motivo de bloqueio correto.
        decisao = self.motor_decisao.decidir(
            contexto, risco_aprovado=pode_operar, motivo_risco=motivo_bloqueio, ha_operacao_aberta=False
        )
        self._notificar_decisao(decisao)
        self.ultima_decisao = decisao

        if not pode_operar or decisao.decisao == Decisao.AGUARDAR:
            return

        if config_scale_out is not None:
            novas_ordens = self.executor.abrir_ordens_scale_out(decisao, config_scale_out)
            self.resultado.ordens_abertas = novas_ordens
            for ordem in novas_ordens:
                if self._ao_abrir_ordem:
                    self._ao_abrir_ordem(ordem)
        else:
            nova_ordem = self.executor.abrir_ordem(decisao, self.quantidade_padrao)
            self.resultado.ordens_abertas = [nova_ordem]
            if self._ao_abrir_ordem:
                self._ao_abrir_ordem(nova_ordem)

    def _gerenciar_scale_out(self, candle: Candle, config) -> None:
        """
        Verifica, na ordem validada no backtest: primeiro os alvos
        individuais de cada contrato, depois o stop compartilhado (que
        vai subindo conforme o preço avança) para o que sobrou.
        """
        if not self.resultado.ordens_abertas:
            return

        primeira = self.resultado.ordens_abertas[0]
        lado = primeira.lado
        preco_entrada = primeira.preco_entrada
        sinal = 1 if lado == Lado.COMPRA else -1
        pontos_ganho = (candle.fechamento - preco_entrada) * sinal

        ordens_restantes = []
        for ordem in self.resultado.ordens_abertas:
            if ordem.alvo_pontos is not None:
                preco_alvo = preco_do_alvo(preco_entrada, lado, ordem.alvo_pontos)
                bateu = (candle.maxima >= preco_alvo) if lado == Lado.COMPRA else (candle.minima <= preco_alvo)
                if bateu:
                    fechada = self.executor.fechar_ordem(
                        ordem, preco_alvo, f"Alvo de {ordem.alvo_pontos:.0f} pontos atingido", candle.timestamp
                    )
                    self._registrar_fechamento(fechada)
                    continue
            ordens_restantes.append(ordem)
        self.resultado.ordens_abertas = ordens_restantes

        if not self.resultado.ordens_abertas:
            return

        stop_pontos = calcular_stop_atual_pontos(pontos_ganho, config)
        preco_stop = preco_do_stop(preco_entrada, lado, stop_pontos)
        stop_atingido = (candle.minima <= preco_stop) if lado == Lado.COMPRA else (candle.maxima >= preco_stop)

        if stop_atingido:
            for ordem in self.resultado.ordens_abertas:
                fechada = self.executor.fechar_ordem(
                    ordem, preco_stop, f"Stop ({stop_pontos:+.0f} pontos em relação à entrada)", candle.timestamp
                )
                self._registrar_fechamento(fechada)
            self.resultado.ordens_abertas = []

    def _notificar_decisao(self, decisao: DecisaoTrade) -> None:
        self.ultima_decisao = decisao
        if self._ao_decidir:
            self._ao_decidir(decisao)

    def _registrar_fechamento(self, ordem_fechada: OrdemSimulada) -> None:
        self.gestor_risco.registrar_resultado(ordem_fechada, ordem_fechada.timestamp_saida)
        self.resultado.ordens_fechadas.append(ordem_fechada)
        self.resultado.resultado_financeiro_total += ordem_fechada.resultado_financeiro or 0.0
        if self._ao_fechar_ordem:
            self._ao_fechar_ordem(ordem_fechada)

    def _avaliar_fechamento_legado(self, contexto: ContextoMercado, decisao: DecisaoTrade) -> None:
        """
        Comportamento legado (fecha no sinal oposto) — usado apenas para
        ativos SEM configuração de scale-out validada (ver
        orders/scale_out.py). Assume no máximo 1 ordem aberta.
        """
        if not self.resultado.ordens_abertas:
            return
        ordem = self.resultado.ordens_abertas[0]

        deve_fechar = (
            (ordem.lado.value == "COMPRA" and decisao.decisao == Decisao.VENDER)
            or (ordem.lado.value == "VENDA" and decisao.decisao == Decisao.COMPRAR)
        )

        if not deve_fechar:
            return

        ordem_fechada = self.executor.fechar_ordem(
            ordem,
            preco_saida=contexto.candle_atual.fechamento,
            motivo_saida="; ".join(decisao.motivos) or "Sinal oposto do motor de decisão",
            timestamp_saida=contexto.candle_atual.timestamp,
        )
        self._registrar_fechamento(ordem_fechada)
        self.resultado.ordens_abertas = []
