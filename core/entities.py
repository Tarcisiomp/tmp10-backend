"""
Entidades de domínio (puro Python, sem dependência de banco ou frameworks).

Essas classes representam os conceitos centrais do negócio e são usadas
por TODOS os módulos (market, indicators, ai, risk, orders, backtest,
simulation). Nada aqui sabe nada sobre SQLAlchemy, FastAPI ou Redis —
isso é o que garante o desacoplamento (Clean Architecture / DDD).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Timeframe(str, Enum):
    M1 = "1m"
    M2 = "2m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    D1 = "1d"


class Decisao(str, Enum):
    COMPRAR = "COMPRAR"
    VENDER = "VENDER"
    AGUARDAR = "AGUARDAR"


class Lado(str, Enum):
    COMPRA = "COMPRA"
    VENDA = "VENDA"


@dataclass(frozen=True)
class Candle:
    """Representa um candle de mercado (OHLCV) em um timeframe específico."""

    ativo: str
    timeframe: Timeframe
    timestamp: datetime
    abertura: float
    maxima: float
    minima: float
    fechamento: float
    volume: float
    volume_financeiro: float | None = None
    vwap: float | None = None


@dataclass(frozen=True)
class TickData:
    """Representa um tick individual (Time & Sales)."""

    ativo: str
    timestamp: datetime
    preco: float
    quantidade: int
    agressor: str | None = None  # "COMPRADOR" | "VENDEDOR" | None


@dataclass(frozen=True)
class BookLevel:
    preco: float
    quantidade: int


@dataclass(frozen=True)
class BookOfertas:
    ativo: str
    timestamp: datetime
    compras: list[BookLevel] = field(default_factory=list)
    vendas: list[BookLevel] = field(default_factory=list)


@dataclass
class IndicadoresSnapshot:
    """
    Conjunto de indicadores calculados para um candle/momento específico.
    Todos os campos são opcionais pois nem todo indicador precisa estar
    presente em toda decisão — o motor de decisão trabalha com o que tiver.
    """

    ema_curta: float | None = None
    ema_longa: float | None = None
    sma: float | None = None
    vwap: float | None = None
    rsi: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    atr: float | None = None
    adx: float | None = None
    bb_superior: float | None = None
    bb_media: float | None = None
    bb_inferior: float | None = None
    estocastico_k: float | None = None
    estocastico_d: float | None = None
    obv: float | None = None
    volume_financeiro: float | None = None


@dataclass
class ContextoMercado:
    """
    Tudo que o motor de decisão recebe para decidir: candle atual,
    indicadores, tendência/volatilidade classificados pela camada de IA.
    """

    ativo: str
    timeframe: Timeframe
    candle_atual: Candle
    indicadores: IndicadoresSnapshot
    tendencia: str | None = None          # ex.: "ALTA", "BAIXA", "LATERAL"
    reversao_detectada: bool = False
    padroes_detectados: list[str] = field(default_factory=list)
    classe_volatilidade: str | None = None  # ex.: "BAIXA", "NORMAL", "ALTA"
    volume_relativo: float | None = None  # volume do candle atual / média do volume recente
    horario: datetime | None = None


@dataclass(frozen=True)
class ItemChecklist:
    """Um item do checklist pré-operação, com o motivo por trás do resultado."""

    item: str
    aprovado: bool
    detalhe: str


@dataclass
class DecisaoTrade:
    """Resultado do motor de decisão: o quê decidir, por quê, e o quão bem embasado."""

    decisao: Decisao
    confianca: float  # 0.0 a 1.0
    motivos: list[str]
    contexto: ContextoMercado
    score_ia: float = 0.0  # 0 a 100 — combinação ponderada dos fatores abaixo
    fatores: dict[str, float] = field(default_factory=dict)  # ex.: {"tendencia": 82.0, "volume": 60.0, ...}
    explicacao: str = ""  # parágrafo em linguagem natural explicando o raciocínio
    checklist: list[ItemChecklist] = field(default_factory=list)
    atividade_ia: str = ""  # ex.: "Analisando mercado…", "Aguardando confirmação…"
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NiveisDeOperacao:
    """Stop e alvos calculados no momento da entrada (baseados em ATR)."""

    stop: float
    alvo_1: float
    alvo_2: float
    alvo_3: float
    risco_por_contrato: float
    retorno_esperado_alvo_1: float
    relacao_risco_retorno: float


@dataclass
class OrdemSimulada:
    """
    Representa uma ordem executada em modo simulado (paper trading).

    Quando a entrada usa saída em partes (scale-out — ver
    `orders/niveis.py` e `simulation/paper_trading.py`), cada contrato
    vira sua PRÓPRIA OrdemSimulada (quantidade=1), todas compartilhando
    o mesmo `grupo_entrada_id` — isso evita ter que inventar um esquema
    novo de "quantidade parcial" dentro de uma única ordem, e reaproveita
    a mesma estrutura de banco que já existia (uma linha por contrato).
    """

    ativo: str
    lado: Lado
    preco_entrada: float
    quantidade: int
    timestamp_entrada: datetime
    motivo_entrada: str
    preco_saida: float | None = None
    timestamp_saida: datetime | None = None
    motivo_saida: str | None = None
    resultado_pontos: float | None = None  # variação de preço, em pontos (sem multiplicar por valor/quantidade)
    resultado_financeiro_bruto: float | None = None  # em R$, antes de custos de bolsa = pontos × valor_por_ponto × quantidade
    custo_b3: float | None = None  # custo de bolsa (emolumentos + liquidação) da operação completa, em R$
    resultado_financeiro: float | None = None  # em R$, JÁ LÍQUIDO de custos de bolsa (não inclui IR, que é apurado mensalmente)
    aberta: bool = True
    niveis: NiveisDeOperacao | None = None
    score_ia_entrada: float | None = None
    confianca_entrada: float | None = None
    grupo_entrada_id: str | None = None  # liga os N contratos da mesma entrada (scale-out)
    alvo_pontos: float | None = None  # alvo fixo (em pontos) deste contrato específico; None = "contrato corredor" (só stop/trailing)
