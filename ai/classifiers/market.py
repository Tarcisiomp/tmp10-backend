"""
Classificadores de mercado e volatilidade.

Implementações de referência baseadas em regras/estatística simples
(placeholders sinalizados), prontas para receber modelos treinados.
"""

import numpy as np

from core.entities import Candle, IndicadoresSnapshot
from core.interfaces import ClassificadorDeVolatilidade


class ClassificadorDeVolatilidadeHeuristico(ClassificadorDeVolatilidade):
    """
    Classifica a volatilidade atual comparando o ATR atual com a média
    histórica de ATR da janela observada.
    """

    def __init__(self, limiar_baixa: float = 0.7, limiar_alta: float = 1.3):
        self.limiar_baixa = limiar_baixa
        self.limiar_alta = limiar_alta

    def classificar(self, candles: list[Candle], indicadores: IndicadoresSnapshot) -> str:
        if indicadores.atr is None or len(candles) < 20:
            return "INDEFINIDO"

        amplitudes = np.array([c.maxima - c.minima for c in candles[-20:]])
        amplitude_media = float(np.mean(amplitudes))
        if amplitude_media == 0:
            return "INDEFINIDO"

        razao = indicadores.atr / amplitude_media
        if razao < self.limiar_baixa:
            return "BAIXA"
        if razao > self.limiar_alta:
            return "ALTA"
        return "NORMAL"


class ClassificadorDeRegimeDeMercado:
    """
    NÃO IMPLEMENTADO NESTA ETAPA.

    Estrutura para um classificador mais amplo de "regime de mercado"
    (ex.: tendência forte, lateralização, alta volatilidade/notícia,
    baixa liquidez) combinando múltiplos sinais — pensado para ser
    alimentado por um modelo supervisionado ou não-supervisionado
    (clustering) treinado sobre o histórico.
    """

    def __init__(self, modelo=None):
        self.modelo = modelo

    def classificar(self, candles: list[Candle], indicadores: IndicadoresSnapshot) -> str:
        raise NotImplementedError("Classificador de regime de mercado será implementado em etapa futura.")
