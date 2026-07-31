"""
Reamostragem de candles — agrupa candles de 1 minuto em timeframes maiores
(2, 5, 15, 60 minutos, etc.), seguindo a regra padrão de agregação OHLCV:

- Abertura: primeiro candle do grupo
- Máxima: maior máxima do grupo
- Mínima: menor mínima do grupo
- Fechamento: último candle do grupo
- Volume: soma dos volumes do grupo

Isso permite rodar o mesmo backtest em vários timeframes sem precisar de
uma fonte de dados separada para cada um — só o candle de 1 minuto (o
mais granular) é necessário; o resto é derivado.
"""

import pandas as pd

from core.entities import Candle, Timeframe

MINUTOS_POR_TIMEFRAME = {
    Timeframe.M1: 1,
    Timeframe.M2: 2,
    Timeframe.M5: 5,
    Timeframe.M15: 15,
    Timeframe.M30: 30,
    Timeframe.H1: 60,
}


def reamostrar_candles(candles: list[Candle], timeframe_destino: Timeframe) -> list[Candle]:
    """
    Recebe candles de 1 minuto (ordem cronológica) e devolve candles
    agregados no timeframe pedido. Se `timeframe_destino` já for M1,
    devolve a lista original sem alterações.
    """
    minutos = MINUTOS_POR_TIMEFRAME.get(timeframe_destino)
    if minutos is None:
        raise ValueError(f"Timeframe não suportado para reamostragem: {timeframe_destino}")
    if minutos == 1:
        return candles
    if not candles:
        return []

    ativo = candles[0].ativo

    df = pd.DataFrame(
        {
            "timestamp": [c.timestamp for c in candles],
            "open": [c.abertura for c in candles],
            "high": [c.maxima for c in candles],
            "low": [c.minima for c in candles],
            "close": [c.fechamento for c in candles],
            "volume": [c.volume for c in candles],
        }
    ).set_index("timestamp")

    # origin="start_day" garante que os agrupamentos comecem alinhados
    # com a abertura do pregão (9:00), não com meia-noite arbitrária.
    agrupado = df.resample(f"{minutos}min", origin="start_day").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    agrupado = agrupado.dropna(subset=["open"])  # remove intervalos sem nenhum candle (fora do pregão)

    return [
        Candle(
            ativo=ativo,
            timeframe=timeframe_destino,
            timestamp=idx.to_pydatetime(),
            abertura=float(row["open"]),
            maxima=float(row["high"]),
            minima=float(row["low"]),
            fechamento=float(row["close"]),
            volume=float(row["volume"]),
        )
        for idx, row in agrupado.iterrows()
    ]
