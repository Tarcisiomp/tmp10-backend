"""
Detector de reversão.

Implementação de referência: heurística baseada em RSI em zona de
sobrecompra/sobrevenda combinado com estocástico. Placeholder claramente
sinalizado, pronto para ser substituído por um modelo treinado.
"""

from core.entities import Candle, IndicadoresSnapshot
from core.interfaces import DetectorDeReversao


class DetectorDeReversaoHeuristico(DetectorDeReversao):
    def __init__(self, rsi_sobrecompra: float = 70.0, rsi_sobrevenda: float = 30.0):
        self.rsi_sobrecompra = rsi_sobrecompra
        self.rsi_sobrevenda = rsi_sobrevenda

    def detectar(self, candles: list[Candle], indicadores: IndicadoresSnapshot) -> bool:
        if indicadores.rsi is None:
            return False

        em_extremo = indicadores.rsi >= self.rsi_sobrecompra or indicadores.rsi <= self.rsi_sobrevenda

        confirmacao_estocastico = False
        if indicadores.estocastico_k is not None and indicadores.estocastico_d is not None:
            confirmacao_estocastico = (
                indicadores.estocastico_k >= 80 or indicadores.estocastico_k <= 20
            )

        return em_extremo and confirmacao_estocastico


class DetectorDeReversaoML(DetectorDeReversao):
    """NÃO TREINADO NESTA ETAPA. Estrutura pronta para modelo futuro."""

    def __init__(self, modelo=None):
        self.modelo = modelo
        self._fallback = DetectorDeReversaoHeuristico()

    def detectar(self, candles: list[Candle], indicadores: IndicadoresSnapshot) -> bool:
        if self.modelo is None:
            return self._fallback.detectar(candles, indicadores)
        raise NotImplementedError("Treinamento do modelo de reversão será feito em etapa futura.")
