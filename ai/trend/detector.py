"""
Detector de tendência.

Implementação de referência: heurística simples baseada em EMA curta vs.
EMA longa e ADX (força da tendência). É um PLACEHOLDER claramente
sinalizado — o objetivo desta etapa é ter a estrutura pronta, não o
modelo final. Nas próximas etapas, esta classe pode ser substituída por
um classificador de ML/PyTorch treinado, desde que implemente a mesma
interface `ClassificadorDeTendencia`.
"""

from core.entities import Candle, IndicadoresSnapshot
from core.interfaces import ClassificadorDeTendencia


class DetectorDeTendenciaHeuristico(ClassificadorDeTendencia):
    """Implementação de referência baseada em regras simples e explícitas."""

    def __init__(self, limiar_adx_tendencia: float = 20.0):
        self.limiar_adx_tendencia = limiar_adx_tendencia

    def classificar(self, candles: list[Candle], indicadores: IndicadoresSnapshot) -> str:
        if indicadores.ema_curta is None or indicadores.ema_longa is None:
            return "INDEFINIDO"

        tendencia_direcao = "ALTA" if indicadores.ema_curta > indicadores.ema_longa else "BAIXA"

        # ADX baixo = mercado sem tendência definida, mesmo que as EMAs estejam levemente separadas
        if indicadores.adx is not None and indicadores.adx < self.limiar_adx_tendencia:
            return "LATERAL"

        return tendencia_direcao


class DetectorDeTendenciaML(ClassificadorDeTendencia):
    """
    NÃO TREINADO NESTA ETAPA.

    Estrutura pronta para receber um modelo de ML/PyTorch treinado com
    dados históricos rotulados. Por enquanto, delega para a versão
    heurística para nunca quebrar o pipeline.
    """

    def __init__(self, modelo=None):
        self.modelo = modelo
        self._fallback = DetectorDeTendenciaHeuristico()

    def classificar(self, candles: list[Candle], indicadores: IndicadoresSnapshot) -> str:
        if self.modelo is None:
            return self._fallback.classificar(candles, indicadores)
        # TODO (próxima etapa): pré-processar `candles`/`indicadores` em
        # features e chamar self.modelo.predict(...) / self.modelo(...)
        raise NotImplementedError("Treinamento do modelo de tendência será feito em etapa futura.")
