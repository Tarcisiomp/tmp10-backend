"""
Models SQLAlchemy — representação em banco das entidades de domínio.

Mantidos separados de core/entities.py de propósito: entidades de domínio
são puras (sem SQLAlchemy), models são a camada de persistência.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class CandleModel(Base):
    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ativo: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    abertura: Mapped[float] = mapped_column(Float)
    maxima: Mapped[float] = mapped_column(Float)
    minima: Mapped[float] = mapped_column(Float)
    fechamento: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    volume_financeiro: Mapped[float | None] = mapped_column(Float, nullable=True)
    vwap: Mapped[float | None] = mapped_column(Float, nullable=True)


class IndicadorModel(Base):
    __tablename__ = "indicadores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candle_id: Mapped[int] = mapped_column(Integer, index=True)
    ativo: Mapped[str] = mapped_column(String(20), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    dados: Mapped[dict] = mapped_column(JSON)  # snapshot completo de IndicadoresSnapshot


class DecisaoModel(Base):
    __tablename__ = "decisoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ativo: Mapped[str] = mapped_column(String(20), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    decisao: Mapped[str] = mapped_column(String(10))  # COMPRAR / VENDER / AGUARDAR
    confianca: Mapped[float] = mapped_column(Float)
    motivos: Mapped[dict] = mapped_column(JSON)  # lista de strings
    contexto: Mapped[dict] = mapped_column(JSON)  # snapshot do contexto usado
    score_ia: Mapped[float] = mapped_column(Float, default=0.0)
    fatores: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"tendencia": 82.0, ...}
    explicacao: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    checklist: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # lista de {item, aprovado, detalhe}
    atividade_ia: Mapped[str | None] = mapped_column(String(100), nullable=True)


class TradeModel(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ativo: Mapped[str] = mapped_column(String(20), index=True)
    origem: Mapped[str] = mapped_column(String(20), default="SIMULACAO")  # SIMULACAO | BACKTEST | REAL (futuro)
    lado: Mapped[str] = mapped_column(String(10))
    preco_entrada: Mapped[float] = mapped_column(Float)
    quantidade: Mapped[int] = mapped_column(Integer)
    timestamp_entrada: Mapped[datetime] = mapped_column(DateTime)
    motivo_entrada: Mapped[str] = mapped_column(String(255))
    preco_saida: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp_saida: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    motivo_saida: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resultado_pontos: Mapped[float | None] = mapped_column(Float, nullable=True)
    resultado_financeiro: Mapped[float | None] = mapped_column(Float, nullable=True)
    aberta: Mapped[bool] = mapped_column(Boolean, default=True)
    niveis: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # stop, alvo_1/2/3, risco, retorno esperado
    score_ia_entrada: Mapped[float | None] = mapped_column(Float, nullable=True)
    confianca_entrada: Mapped[float | None] = mapped_column(Float, nullable=True)
    grupo_entrada_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)  # liga os N contratos da mesma entrada (scale-out)
    alvo_pontos: Mapped[float | None] = mapped_column(Float, nullable=True)  # alvo fixo deste contrato específico; None = "corredor" (só stop/trailing)


class LogModel(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    nivel: Mapped[str] = mapped_column(String(10))  # INFO, WARNING, ERROR
    modulo: Mapped[str] = mapped_column(String(50))
    mensagem: Mapped[str] = mapped_column(String(1000))
    dados_extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class BacktestModel(Base):
    __tablename__ = "backtests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ativo: Mapped[str] = mapped_column(String(20), index=True)
    data_inicio: Mapped[datetime] = mapped_column(DateTime)
    data_fim: Mapped[datetime] = mapped_column(DateTime)
    executado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    win_rate: Mapped[float] = mapped_column(Float)
    profit_factor: Mapped[float] = mapped_column(Float)
    payoff: Mapped[float] = mapped_column(Float)
    drawdown_maximo: Mapped[float] = mapped_column(Float)
    lucro_liquido: Mapped[float] = mapped_column(Float)
    quantidade_operacoes: Mapped[int] = mapped_column(Integer)
    expectativa_matematica: Mapped[float] = mapped_column(Float)
    curva_capital: Mapped[dict] = mapped_column(JSON)  # lista de pontos [{ "t": ..., "capital": ... }]
    parametros: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SimulacaoModel(Base):
    __tablename__ = "simulacoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ativo: Mapped[str] = mapped_column(String(20), index=True)
    iniciado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)
    resultado_financeiro_total: Mapped[float] = mapped_column(Float, default=0.0)
    quantidade_operacoes: Mapped[int] = mapped_column(Integer, default=0)


class ImpostoMensalModel(Base):
    """Guarda o status Pago/Pendente de cada mês — isso é uma decisão do usuário, não é calculado."""

    __tablename__ = "impostos_mensais"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ano: Mapped[int] = mapped_column(Integer, index=True)
    mes: Mapped[int] = mapped_column(Integer)  # 1-12
    pago: Mapped[bool] = mapped_column(Boolean, default=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("ano", "mes", name="uq_ano_mes"),)


class CustoOperacionalModel(Base):
    """
    Custos operacionais reais (corretagem, emolumentos, registro,
    liquidação, ISS, outras taxas), configuráveis por ativo + corretora
    — SUBSTITUI qualquer taxa fixa no código. Toda a Taxa Total por
    Contrato é calculada a partir daqui, nunca escrita direto no código.

    Pode haver mais de um registro para o mesmo ativo+corretora (ex:
    quando a B3 muda uma taxa) — o registro vigente é o de
    `data_inicio_vigencia` mais recente que já passou, com `ativo_padrao`
    marcado como True.
    """

    __tablename__ = "custos_operacionais"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ativo: Mapped[str] = mapped_column(String(20), index=True)  # WIN, WDO, IND, DOL, ações, etc — qualquer texto
    corretora: Mapped[str] = mapped_column(String(50), index=True)  # Clear, XP, BTG, etc — qualquer texto
    corretagem: Mapped[float] = mapped_column(Float, default=0.0)
    emolumentos: Mapped[float] = mapped_column(Float, default=0.0)
    registro: Mapped[float] = mapped_column(Float, default=0.0)
    liquidacao: Mapped[float] = mapped_column(Float, default=0.0)
    iss: Mapped[float] = mapped_column(Float, default=0.0)
    outras_taxas: Mapped[dict] = mapped_column(JSON, default=list)  # lista de {"nome": str, "valor": float}
    taxa_total_contrato: Mapped[float] = mapped_column(Float, default=0.0)  # calculado automaticamente, guardado pra consulta rápida
    data_inicio_vigencia: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ativo_padrao: Mapped[bool] = mapped_column(Boolean, default=True)  # "ativado" (ver tela de Ativar/Inativar) — nome mantido igual ao pedido original
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConfiguracaoModel(Base):
    __tablename__ = "configuracoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chave: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    valor: Mapped[dict] = mapped_column(JSON)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
