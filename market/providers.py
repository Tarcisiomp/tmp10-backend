"""
Provedores de dados de mercado.

Hoje existem duas implementações:
- HistoricoCSVProvider: lê candles de um CSV/dataframe para backtest.
- SimuladoProvider: gera/repassa candles em "tempo real" simulado, útil
  para o paper trading enquanto não há feed ao vivo.

A integração real com o Profit Pro entra aqui futuramente, implementando
a mesma interface `ProvedorDeDadosDeMercado` (ver core/interfaces.py),
sem precisar alterar indicators/, ai/, risk/ ou orders/.
"""

from datetime import datetime

import pandas as pd

from core.entities import Candle, Timeframe
from core.interfaces import ProvedorDeDadosDeMercado


class HistoricoCSVProvider(ProvedorDeDadosDeMercado):
    """
    Lê um arquivo CSV com colunas: timestamp, open, high, low, close, volume
    (e opcionalmente volume_financeiro, vwap) e serve como fonte de candles
    para o backtest.
    """

    def __init__(self, caminho_csv: str, ativo: str, timeframe: Timeframe = Timeframe.M1):
        self.ativo = ativo
        self.timeframe = timeframe
        self._df = pd.read_csv(caminho_csv, parse_dates=["timestamp"])
        self._df = self._df.sort_values("timestamp").reset_index(drop=True)

    def obter_candles(self, ativo: str, timeframe: str, limite: int) -> list[Candle]:
        subset = self._df.tail(limite)
        return [
            Candle(
                ativo=self.ativo,
                timeframe=self.timeframe,
                timestamp=row["timestamp"].to_pydatetime()
                if isinstance(row["timestamp"], pd.Timestamp)
                else row["timestamp"],
                abertura=float(row["open"]),
                maxima=float(row["high"]),
                minima=float(row["low"]),
                fechamento=float(row["close"]),
                volume=float(row["volume"]),
                volume_financeiro=float(row.get("volume_financeiro", 0.0) or 0.0) or None,
                vwap=float(row.get("vwap", 0.0) or 0.0) or None,
            )
            for _, row in subset.iterrows()
        ]

    def todos_os_candles(self) -> list[Candle]:
        """Usado pelo motor de backtest para varrer o histórico inteiro."""
        return self.obter_candles(self.ativo, self.timeframe.value, limite=len(self._df))


class SimuladoProvider(ProvedorDeDadosDeMercado):
    """
    Provider "vivo" simulado: mantém um buffer de candles em memória e
    permite empurrar novos candles (via `adicionar_candle`), simulando
    a chegada de dados em tempo real enquanto não há integração real.
    """

    def __init__(self, ativo: str, timeframe: Timeframe = Timeframe.M1):
        self.ativo = ativo
        self.timeframe = timeframe
        self._buffer: list[Candle] = []

    def adicionar_candle(self, candle: Candle) -> None:
        self._buffer.append(candle)

    def obter_candles(self, ativo: str, timeframe: str, limite: int) -> list[Candle]:
        return self._buffer[-limite:]


# --- Placeholder explícito para a integração futura ---
class ProfitProProvider(ProvedorDeDadosDeMercado):
    """
    NÃO IMPLEMENTADO NESTA ETAPA.

    Aqui entrará a integração real com o Profit Pro (DDE/ProfitDLL ou API
    equivalente), recebendo tick, candles, volume, VWAP, book de ofertas e
    Time & Sales em tempo real. Por enquanto, levanta erro proposital para
    deixar claro que não deve ser usado ainda.
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "Integração com o Profit Pro será implementada em uma etapa futura. "
            "Use HistoricoCSVProvider (backtest) ou SimuladoProvider (paper trading) por enquanto."
        )

    def obter_candles(self, ativo: str, timeframe: str, limite: int) -> list[Candle]:
        raise NotImplementedError
