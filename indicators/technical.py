"""
Indicadores técnicos — cada um é uma função pura e independente.

Todos recebem uma lista de `Candle` (do mais antigo para o mais recente)
e retornam valores numéricos (ou None quando não há dados suficientes).
Nenhum indicador conhece o motor de decisão nem a gestão de risco —
eles apenas calculam. Isso permite adicionar, remover ou trocar
indicadores sem tocar em mais nada.
"""

from __future__ import annotations

import numpy as np

from core.entities import Candle, IndicadoresSnapshot


def _closes(candles: list[Candle]) -> np.ndarray:
    return np.array([c.fechamento for c in candles], dtype=float)


def _highs(candles: list[Candle]) -> np.ndarray:
    return np.array([c.maxima for c in candles], dtype=float)


def _lows(candles: list[Candle]) -> np.ndarray:
    return np.array([c.minima for c in candles], dtype=float)


def _volumes(candles: list[Candle]) -> np.ndarray:
    return np.array([c.volume for c in candles], dtype=float)


def sma(candles: list[Candle], periodo: int) -> float | None:
    closes = _closes(candles)
    if len(closes) < periodo:
        return None
    return float(np.mean(closes[-periodo:]))


def ema(candles: list[Candle], periodo: int) -> float | None:
    closes = _closes(candles)
    if len(closes) < periodo:
        return None
    alpha = 2 / (periodo + 1)
    valor = closes[0]
    for preco in closes[1:]:
        valor = alpha * preco + (1 - alpha) * valor
    return float(valor)


def vwap(candles: list[Candle]) -> float | None:
    if not candles:
        return None
    total_vol = sum(c.volume for c in candles)
    if total_vol == 0:
        return None
    total_pv = sum(((c.maxima + c.minima + c.fechamento) / 3) * c.volume for c in candles)
    return float(total_pv / total_vol)


def rsi(candles: list[Candle], periodo: int = 14) -> float | None:
    closes = _closes(candles)
    if len(closes) < periodo + 1:
        return None
    deltas = np.diff(closes)
    ganhos = np.where(deltas > 0, deltas, 0.0)
    perdas = np.where(deltas < 0, -deltas, 0.0)
    media_ganho = np.mean(ganhos[-periodo:])
    media_perda = np.mean(perdas[-periodo:])
    if media_perda == 0:
        return 100.0
    rs = media_ganho / media_perda
    return float(100 - (100 / (1 + rs)))


def macd(
    candles: list[Candle], periodo_curto: int = 12, periodo_longo: int = 26, periodo_signal: int = 9
) -> tuple[float | None, float | None, float | None]:
    """Retorna (macd, signal, histograma)."""
    closes = _closes(candles)
    if len(closes) < periodo_longo + periodo_signal:
        return None, None, None

    def _ema_serie(serie: np.ndarray, periodo: int) -> np.ndarray:
        alpha = 2 / (periodo + 1)
        resultado = np.empty_like(serie)
        resultado[0] = serie[0]
        for i in range(1, len(serie)):
            resultado[i] = alpha * serie[i] + (1 - alpha) * resultado[i - 1]
        return resultado

    ema_curta = _ema_serie(closes, periodo_curto)
    ema_longa = _ema_serie(closes, periodo_longo)
    linha_macd = ema_curta - ema_longa
    linha_signal = _ema_serie(linha_macd, periodo_signal)
    histograma = linha_macd - linha_signal
    return float(linha_macd[-1]), float(linha_signal[-1]), float(histograma[-1])


def atr(candles: list[Candle], periodo: int = 14) -> float | None:
    if len(candles) < periodo + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        atual = candles[i]
        anterior = candles[i - 1]
        tr = max(
            atual.maxima - atual.minima,
            abs(atual.maxima - anterior.fechamento),
            abs(atual.minima - anterior.fechamento),
        )
        trs.append(tr)
    trs = np.array(trs[-periodo:])
    return float(np.mean(trs))


def adx(candles: list[Candle], periodo: int = 14) -> float | None:
    if len(candles) < periodo + 1:
        return None

    highs = _highs(candles)
    lows = _lows(candles)
    closes = _closes(candles)

    plus_dm = np.zeros(len(candles))
    minus_dm = np.zeros(len(candles))
    trs = np.zeros(len(candles))

    for i in range(1, len(candles)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
        trs[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )

    atr_suave = np.mean(trs[-periodo:])
    if atr_suave == 0:
        return None
    plus_di = 100 * (np.mean(plus_dm[-periodo:]) / atr_suave)
    minus_di = 100 * (np.mean(minus_dm[-periodo:]) / atr_suave)
    soma_di = plus_di + minus_di
    if soma_di == 0:
        return 0.0
    dx = 100 * abs(plus_di - minus_di) / soma_di
    return float(dx)


def bandas_bollinger(candles: list[Candle], periodo: int = 20, desvios: float = 2.0) -> tuple[
    float | None, float | None, float | None
]:
    """Retorna (banda_superior, media, banda_inferior)."""
    closes = _closes(candles)
    if len(closes) < periodo:
        return None, None, None
    janela = closes[-periodo:]
    media = float(np.mean(janela))
    desvio_padrao = float(np.std(janela))
    return media + desvios * desvio_padrao, media, media - desvios * desvio_padrao


def estocastico(candles: list[Candle], periodo: int = 14, periodo_d: int = 3) -> tuple[float | None, float | None]:
    """Retorna (%K, %D)."""
    if len(candles) < periodo + periodo_d:
        return None, None
    highs = _highs(candles)
    lows = _lows(candles)
    closes = _closes(candles)

    ks = []
    for i in range(periodo - 1, len(candles)):
        janela_high = highs[i - periodo + 1 : i + 1]
        janela_low = lows[i - periodo + 1 : i + 1]
        maior = np.max(janela_high)
        menor = np.min(janela_low)
        if maior == menor:
            ks.append(50.0)
        else:
            ks.append(100 * (closes[i] - menor) / (maior - menor))

    k_atual = ks[-1]
    d_atual = float(np.mean(ks[-periodo_d:])) if len(ks) >= periodo_d else None
    return float(k_atual), d_atual


def obv(candles: list[Candle]) -> float | None:
    if len(candles) < 2:
        return None
    valor = 0.0
    for i in range(1, len(candles)):
        if candles[i].fechamento > candles[i - 1].fechamento:
            valor += candles[i].volume
        elif candles[i].fechamento < candles[i - 1].fechamento:
            valor -= candles[i].volume
    return float(valor)


def volume_financeiro(candles: list[Candle]) -> float | None:
    if not candles:
        return None
    ultimo = candles[-1]
    if ultimo.volume_financeiro is not None:
        return ultimo.volume_financeiro
    # aproximação: preço médio do candle * volume, quando o dado não vem pronto
    preco_medio = (ultimo.maxima + ultimo.minima + ultimo.fechamento) / 3
    return float(preco_medio * ultimo.volume)


def calcular_snapshot(candles: list[Candle]) -> IndicadoresSnapshot:
    """
    Calcula todos os indicadores de uma vez e devolve um IndicadoresSnapshot
    pronto para ser usado pela camada de IA / motor de decisão.
    """
    macd_valor, macd_signal, macd_hist = macd(candles)
    bb_sup, bb_media, bb_inf = bandas_bollinger(candles)
    est_k, est_d = estocastico(candles)

    return IndicadoresSnapshot(
        ema_curta=ema(candles, 9),
        ema_longa=ema(candles, 21),
        sma=sma(candles, 20),
        vwap=vwap(candles),
        rsi=rsi(candles),
        macd=macd_valor,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
        atr=atr(candles),
        adx=adx(candles),
        bb_superior=bb_sup,
        bb_media=bb_media,
        bb_inferior=bb_inf,
        estocastico_k=est_k,
        estocastico_d=est_d,
        obv=obv(candles),
        volume_financeiro=volume_financeiro(candles),
    )
