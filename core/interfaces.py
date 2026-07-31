"""
Contratos (interfaces) entre módulos.

Isso é o que permite trocar peças do sistema sem quebrar o resto:
por exemplo, trocar o MotorDeDecisao de "baseado em regras" para
"baseado em rede neural" sem mexer em risk/ ou orders/, porque
ambos dependem apenas desta interface, nunca da implementação concreta.
"""

from abc import ABC, abstractmethod

from core.entities import (
    Candle,
    ContextoMercado,
    DecisaoTrade,
    IndicadoresSnapshot,
    OrdemSimulada,
)


class ClassificadorDeTendencia(ABC):
    @abstractmethod
    def classificar(self, candles: list[Candle], indicadores: IndicadoresSnapshot) -> str:
        """Retorna algo como 'ALTA', 'BAIXA' ou 'LATERAL'."""
        raise NotImplementedError


class DetectorDeReversao(ABC):
    @abstractmethod
    def detectar(self, candles: list[Candle], indicadores: IndicadoresSnapshot) -> bool:
        raise NotImplementedError


class ReconhecedorDePadroes(ABC):
    @abstractmethod
    def reconhecer(self, candles: list[Candle]) -> list[str]:
        """Retorna lista de padrões identificados (ex.: ['ENGOLFO_ALTA'])."""
        raise NotImplementedError


class ClassificadorDeVolatilidade(ABC):
    @abstractmethod
    def classificar(self, candles: list[Candle], indicadores: IndicadoresSnapshot) -> str:
        """Retorna algo como 'BAIXA', 'NORMAL' ou 'ALTA'."""
        raise NotImplementedError


class MotorDeDecisao(ABC):
    @abstractmethod
    def decidir(
        self, contexto: ContextoMercado, risco_aprovado: bool = True, motivo_risco: str = "", ha_operacao_aberta: bool = False
    ) -> DecisaoTrade:
        """
        Recebe o contexto completo (candle, indicadores, tendência,
        reversão, padrões, volatilidade) e retorna COMPRAR / VENDER /
        AGUARDAR, sempre com os motivos, o Score da IA, o detalhamento
        por fator, a explicação em linguagem natural e o checklist
        pré-operação.
        """
        raise NotImplementedError


class GestorDeRisco(ABC):
    @abstractmethod
    def pode_operar(self, agora=None, score_ia: float | None = None) -> tuple[bool, str]:
        """
        Retorna (True, '') se pode operar, ou (False, motivo do bloqueio).
        `agora` é opcional: quando informado (ex.: pelo backtest, usando o
        timestamp do candle histórico), é usado para checar o horário de
        pregão em vez do relógio real — importante para testes e backtest.
        `score_ia` é opcional: quando informado, é comparado contra o
        score mínimo configurado para autorizar novas operações.
        """
        raise NotImplementedError

    @abstractmethod
    def registrar_resultado(self, ordem: OrdemSimulada, agora=None) -> None:
        """
        `agora` é opcional: quando informado (ex.: pelo backtest, usando o
        timestamp do candle histórico), é usado para checar a virada de dia
        em vez do relógio real — essencial para que os limites diários
        (stop, meta, máx. operações) reiniciem corretamente durante um
        backtest ou qualquer replay de dados históricos.
        """
        raise NotImplementedError


class ExecutorDeOrdens(ABC):
    @abstractmethod
    def abrir_ordem(self, decisao: DecisaoTrade, quantidade: int) -> OrdemSimulada:
        raise NotImplementedError

    @abstractmethod
    def fechar_ordem(
        self, ordem: OrdemSimulada, preco_saida: float, motivo_saida: str, timestamp_saida=None
    ) -> OrdemSimulada:
        """
        `timestamp_saida` é opcional: quando informado (ex.: pelo backtest,
        usando o timestamp do candle histórico), é usado no lugar do
        relógio real — essencial para que "tempo da operação" fique
        correto ao rodar sobre dados históricos.
        """
        raise NotImplementedError


class ProvedorDeDadosDeMercado(ABC):
    """
    Contrato para qualquer fonte de dados de mercado: histórico (backtest),
    simulado (paper trading) ou futuramente ao vivo (Profit Pro).
    """

    @abstractmethod
    def obter_candles(self, ativo: str, timeframe: str, limite: int) -> list[Candle]:
        raise NotImplementedError
