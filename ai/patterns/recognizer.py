"""
Reconhecimento de padrões gráficos (candlestick patterns).

Implementação de referência: detecta um punhado de padrões clássicos de
candle usando regras geométricas simples (corpo, sombra, comparação com
o candle anterior). Isso NÃO é reconhecimento visual/computer vision —
essa parte fica para uma etapa futura (conforme o próprio pedido original
menciona "preparar estrutura para futuramente salvar imagens do gráfico").
"""

from core.entities import Candle
from core.interfaces import ReconhecedorDePadroes


def _corpo(c: Candle) -> float:
    return abs(c.fechamento - c.abertura)


def _sombra_superior(c: Candle) -> float:
    return c.maxima - max(c.abertura, c.fechamento)


def _sombra_inferior(c: Candle) -> float:
    return min(c.abertura, c.fechamento) - c.minima


def _is_doji(c: Candle, tolerancia: float = 0.1) -> bool:
    amplitude = c.maxima - c.minima
    if amplitude == 0:
        return False
    return _corpo(c) / amplitude < tolerancia


def _is_martelo(c: Candle) -> bool:
    corpo = _corpo(c)
    if corpo == 0:
        return False
    return _sombra_inferior(c) >= 2 * corpo and _sombra_superior(c) <= corpo * 0.5


def _is_engolfo_alta(anterior: Candle, atual: Candle) -> bool:
    return (
        anterior.fechamento < anterior.abertura  # candle anterior de baixa
        and atual.fechamento > atual.abertura  # candle atual de alta
        and atual.fechamento >= anterior.abertura
        and atual.abertura <= anterior.fechamento
    )


def _is_engolfo_baixa(anterior: Candle, atual: Candle) -> bool:
    return (
        anterior.fechamento > anterior.abertura  # candle anterior de alta
        and atual.fechamento < atual.abertura  # candle atual de baixa
        and atual.abertura >= anterior.fechamento
        and atual.fechamento <= anterior.abertura
    )


def _range(c: Candle) -> float:
    return c.maxima - c.minima


def _is_rompimento_alta(c4: Candle, c3: Candle, c2: Candle, c1: Candle, atual: Candle) -> bool:
    """
    Padrão descrito pelo usuário: 3+ candles verdes seguidos, depois um
    candle vermelho de correção com range MENOR que o candle anterior,
    depois rompimento (fecha acima da máxima do candle de correção).
    """
    verdes3 = c4.fechamento > c4.abertura and c3.fechamento > c3.abertura and c2.fechamento > c2.abertura
    vermelha_pequena = c1.fechamento < c1.abertura and _range(c1) <= _range(c2)
    return verdes3 and vermelha_pequena and atual.fechamento > c1.maxima


def _is_rompimento_baixa(c4: Candle, c3: Candle, c2: Candle, c1: Candle, atual: Candle) -> bool:
    """Espelho de _is_rompimento_alta, para tendência de baixa."""
    vermelhas3 = c4.fechamento < c4.abertura and c3.fechamento < c3.abertura and c2.fechamento < c2.abertura
    verde_pequena = c1.fechamento > c1.abertura and _range(c1) <= _range(c2)
    return vermelhas3 and verde_pequena and atual.fechamento < c1.minima


class ReconhecedorDePadroesHeuristico(ReconhecedorDePadroes):
    """Implementação de referência com padrões clássicos de candle."""

    def reconhecer(self, candles: list[Candle]) -> list[str]:
        if not candles:
            return []

        padroes: list[str] = []
        atual = candles[-1]

        if _is_doji(atual):
            padroes.append("DOJI")
        if _is_martelo(atual):
            padroes.append("MARTELO")

        if len(candles) >= 2:
            anterior = candles[-2]
            if _is_engolfo_alta(anterior, atual):
                padroes.append("ENGOLFO_ALTA")
            if _is_engolfo_baixa(anterior, atual):
                padroes.append("ENGOLFO_BAIXA")

        if len(candles) >= 5:
            c1, c2, c3, c4 = candles[-2], candles[-3], candles[-4], candles[-5]
            if _is_rompimento_alta(c4, c3, c2, c1, atual):
                padroes.append("ROMPIMENTO_ALTA")
            if _is_rompimento_baixa(c4, c3, c2, c1, atual):
                padroes.append("ROMPIMENTO_BAIXA")

        return padroes


class ReconhecedorDePadroesVisual(ReconhecedorDePadroes):
    """
    NÃO IMPLEMENTADO NESTA ETAPA.

    Estrutura para, futuramente, renderizar o gráfico como imagem e usar
    um modelo de visão computacional (ex.: CNN em PyTorch) para
    reconhecer padrões gráficos mais complexos (OCO, triângulos,
    bandeiras, etc.) a partir da imagem em vez de regras geométricas.
    """

    def __init__(self, modelo=None):
        self.modelo = modelo
        self._fallback = ReconhecedorDePadroesHeuristico()

    def reconhecer(self, candles: list[Candle]) -> list[str]:
        if self.modelo is None:
            return self._fallback.reconhecer(candles)
        raise NotImplementedError("Reconhecimento visual de padrões será implementado em etapa futura.")
