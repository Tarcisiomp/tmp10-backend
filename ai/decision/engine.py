"""
Motor de Decisão.

Este é o único módulo que decide COMPRAR / VENDER / AGUARDAR. Ele recebe
um ContextoMercado já enriquecido (indicadores + tendência + reversão +
padrões + volatilidade, calculados por outros módulos) e SEMPRE retorna:

- a decisão e sua confiança (0 a 1)
- os motivos, em texto
- o Score da IA (0 a 100) e o detalhamento por fator (tendência, volume,
  fluxo, volatilidade, momentum, contexto)
- uma explicação em linguagem natural do raciocínio
- o checklist pré-operação
- um rótulo do que a IA "está fazendo agora"

A implementação de referência (`MotorDeDecisaoHeuristico`) combina
tendência + reversão + padrões + volatilidade de forma explícita e
comentada, exatamente para servir de baseline mensurável antes de
qualquer modelo de IA/ML entrar em cena. Ela NÃO promete lucro nem usa
regras fixas de cruzamento de médias isoladas — é um combinador de
múltiplos sinais com pesos explícitos e ajustáveis.

Para trocar por um modelo de IA, basta criar uma nova classe que
implemente `MotorDeDecisao` (ver core/interfaces.py) e injetá-la no lugar
desta em simulation/ e backtest/.
"""

from ai.decision.checklist import gerar_checklist
from ai.decision.narrativa import gerar_atividade_ia, gerar_explicacao
from ai.decision.scoring import calcular_fatores, calcular_score_ia
from core.entities import ContextoMercado, Decisao, DecisaoTrade
from core.interfaces import MotorDeDecisao


class MotorDeDecisaoHeuristico(MotorDeDecisao):
    def __init__(self, confianca_minima_para_operar: float = 0.55):
        self.confianca_minima_para_operar = confianca_minima_para_operar

    def decidir(
        self, contexto: ContextoMercado, risco_aprovado: bool = True, motivo_risco: str = "", ha_operacao_aberta: bool = False
    ) -> DecisaoTrade:
        motivos: list[str] = []
        pontos_compra = 0.0
        pontos_venda = 0.0

        # --- Tendência ---
        if contexto.tendencia == "ALTA":
            pontos_compra += 1.0
            motivos.append("Tendência classificada como ALTA")
        elif contexto.tendencia == "BAIXA":
            pontos_venda += 1.0
            motivos.append("Tendência classificada como BAIXA")
        elif contexto.tendencia == "LATERAL":
            motivos.append("Mercado lateral: sem tendência definida (ADX baixo)")

        # --- Reversão ---
        if contexto.reversao_detectada:
            if contexto.tendencia == "ALTA":
                pontos_venda += 0.8
                motivos.append("Sinal de reversão detectado durante tendência de alta")
            elif contexto.tendencia == "BAIXA":
                pontos_compra += 0.8
                motivos.append("Sinal de reversão detectado durante tendência de baixa")

        # --- Padrões gráficos ---
        if "ENGOLFO_ALTA" in contexto.padroes_detectados:
            pontos_compra += 0.6
            motivos.append("padrão de engolfo de alta identificado")
        if "ENGOLFO_BAIXA" in contexto.padroes_detectados:
            pontos_venda += 0.6
            motivos.append("padrão de engolfo de baixa identificado")
        if "MARTELO" in contexto.padroes_detectados:
            pontos_compra += 0.3
            motivos.append("padrão de martelo identificado")
        if "DOJI" in contexto.padroes_detectados:
            motivos.append("doji identificado: indecisão do mercado")

        # --- Indicadores de momentum ---
        ind = contexto.indicadores
        if ind.rsi is not None:
            if ind.rsi <= 30:
                pontos_compra += 0.4
                motivos.append(f"RSI em zona de sobrevenda ({ind.rsi:.1f})")
            elif ind.rsi >= 70:
                pontos_venda += 0.4
                motivos.append(f"RSI em zona de sobrecompra ({ind.rsi:.1f})")

        if ind.macd_hist is not None:
            if ind.macd_hist > 0:
                pontos_compra += 0.3
                motivos.append("histograma do MACD positivo")
            elif ind.macd_hist < 0:
                pontos_venda += 0.3
                motivos.append("histograma do MACD negativo")

        # --- Volume ---
        if contexto.volume_relativo is not None and contexto.volume_relativo >= 1.2:
            motivos.append(f"volume {contexto.volume_relativo:.1f}x acima da média recente")

        # --- Filtro de volatilidade ---
        penalidade_volatilidade = 0.0
        if contexto.classe_volatilidade == "ALTA":
            penalidade_volatilidade = 0.3
            motivos.append("volatilidade classificada como ALTA: confiança reduzida por segurança")

        total_pontos = pontos_compra + pontos_venda

        if total_pontos == 0:
            direcao_avaliada = "ALTA" if contexto.tendencia != "BAIXA" else "BAIXA"
            return self._montar_resultado(
                contexto,
                Decisao.AGUARDAR,
                0.0,
                motivos or ["Nenhum sinal relevante identificado"],
                direcao_avaliada,
                risco_aprovado,
                motivo_risco,
                ha_operacao_aberta,
            )

        if pontos_compra > pontos_venda:
            direcao_avaliada = "ALTA"
            confianca = max(0.0, (pontos_compra / total_pontos) - penalidade_volatilidade)
            decisao_final = Decisao.COMPRAR if confianca >= self.confianca_minima_para_operar else Decisao.AGUARDAR
        elif pontos_venda > pontos_compra:
            direcao_avaliada = "BAIXA"
            confianca = max(0.0, (pontos_venda / total_pontos) - penalidade_volatilidade)
            decisao_final = Decisao.VENDER if confianca >= self.confianca_minima_para_operar else Decisao.AGUARDAR
        else:
            direcao_avaliada = "ALTA"
            confianca = 0.5
            decisao_final = Decisao.AGUARDAR
            motivos.append("sinais de compra e venda empatados")

        if decisao_final == Decisao.AGUARDAR and confianca < self.confianca_minima_para_operar:
            motivos.append(
                f"confiança calculada ({confianca:.2f}) abaixo do mínimo exigido "
                f"({self.confianca_minima_para_operar:.2f}) para operar"
            )

        return self._montar_resultado(
            contexto,
            decisao_final,
            round(confianca, 3),
            motivos,
            direcao_avaliada,
            risco_aprovado,
            motivo_risco,
            ha_operacao_aberta,
        )

    def _montar_resultado(
        self,
        contexto: ContextoMercado,
        decisao: Decisao,
        confianca: float,
        motivos: list[str],
        direcao_avaliada: str,
        risco_aprovado: bool,
        motivo_risco: str,
        ha_operacao_aberta: bool,
    ) -> DecisaoTrade:
        fatores = calcular_fatores(contexto, direcao_avaliada)
        score_ia = calcular_score_ia(fatores)
        checklist = gerar_checklist(contexto, direcao_avaliada, risco_aprovado, motivo_risco)
        explicacao = gerar_explicacao(contexto, decisao, motivos, score_ia)
        atividade = gerar_atividade_ia(contexto, decisao, ha_operacao_aberta)

        return DecisaoTrade(
            decisao=decisao,
            confianca=confianca,
            motivos=motivos,
            contexto=contexto,
            score_ia=score_ia,
            fatores=fatores,
            explicacao=explicacao,
            checklist=checklist,
            atividade_ia=atividade,
            timestamp=contexto.candle_atual.timestamp,
        )


class MotorDeDecisaoML(MotorDeDecisao):
    """
    NÃO TREINADO NESTA ETAPA.

    Estrutura pronta para receber um modelo de ML/PyTorch treinado a
    partir dos registros de decisões e resultados salvos no banco
    (tabela `decisoes` + `trades`), fechando o ciclo de "aprender com
    operações anteriores" mencionado no objetivo do projeto.
    """

    def __init__(self, modelo=None):
        self.modelo = modelo
        self._fallback = MotorDeDecisaoHeuristico()

    def decidir(self, contexto: ContextoMercado, **kwargs) -> DecisaoTrade:
        if self.modelo is None:
            return self._fallback.decidir(contexto, **kwargs)
        raise NotImplementedError("Treinamento e inferência do motor de decisão por ML: etapa futura.")
