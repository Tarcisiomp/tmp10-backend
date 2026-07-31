"""
Rotas da API que alimentam o painel/dashboard.

Todos os endpoints retornam dados reais do banco (quando existirem) e
valores/placeholders explícitos quando ainda não há dados suficientes
(ex.: sistema recém-instalado ou nenhum modelo de IA treinado ainda) —
nunca números inventados para "parecer bonito".
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import DecisaoModel, TradeModel
from database.repository import (
    obter_comparacao_ia_mercado,
    obter_configuracoes,
    obter_diario_ia,
    obter_evolucao_ia,
    obter_performance_por_dia_semana,
    obter_performance_por_horario,
    obter_resultados_operacoes_abertas,
    salvar_configuracoes,
)
from financeiro.configuracao import CONFIG_FINANCEIRA_PADRAO
from market.pregao import obter_status_pregao

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
router_financeiro = APIRouter(prefix="/financeiro", tags=["financeiro"])

VERSAO_IA = "v0.1-heuristica"  # atualize aqui quando um modelo treinado entrar em produção
INICIO_PROCESSO = datetime.utcnow()  # usado para "tempo online" — reinicia a cada deploy/restart


@router.get("/status")
def status_sistema(db: Session = Depends(get_db)) -> dict:
    pregao = obter_status_pregao()

    ultima_entrada = db.execute(
        select(TradeModel.timestamp_entrada).order_by(TradeModel.timestamp_entrada.desc()).limit(1)
    ).scalar()
    ultimo_trade_fechado = db.execute(
        select(TradeModel.timestamp_saida)
        .where(TradeModel.aberta.is_(False))
        .order_by(TradeModel.timestamp_saida.desc())
        .limit(1)
    ).scalar()

    return {
        "sistema": "online",
        "ia_versao": VERSAO_IA,
        "ia_status": "estrutura heurística ativa (nenhum modelo de ML treinado nesta etapa)",
        "modo": "PAPER_TRADING",
        "pregao": {
            "aberto": pregao.aberto,
            "aceita_novas_operacoes": pregao.aceita_novas_operacoes,
            "motivo": pregao.motivo,
            "horario_atual": pregao.horario_atual.strftime("%H:%M:%S"),
            "horario_fechamento": pregao.horario_fechamento.strftime("%H:%M:%S"),
        },
        "cronometro": {
            "ultima_entrada": ultima_entrada.isoformat() if ultima_entrada else None,
            "ultimo_trade_fechado": ultimo_trade_fechado.isoformat() if ultimo_trade_fechado else None,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/decisao-atual")
def decisao_atual(db: Session = Depends(get_db)) -> dict:
    """
    Última decisão registrada pela IA: Score, fatores, explicação,
    checklist e o que a IA está "fazendo agora".
    """
    ultima = db.execute(
        select(DecisaoModel).order_by(DecisaoModel.timestamp.desc()).limit(1)
    ).scalars().first()

    if not ultima:
        return {"decisao": None}

    return {
        "decisao": {
            "ativo": ultima.ativo,
            "decisao": ultima.decisao,
            "confianca": ultima.confianca,
            "score_ia": ultima.score_ia,
            "fatores": ultima.fatores,
            "explicacao": ultima.explicacao,
            "checklist": ultima.checklist,
            "atividade_ia": ultima.atividade_ia,
            "motivos": ultima.motivos,
            "timestamp": ultima.timestamp.isoformat(),
        }
    }


@router.get("/operacao-atual")
def operacao_atual(db: Session = Depends(get_db)) -> dict:
    """
    Todas as operações abertas no momento — pode ser mais de uma quando
    o sistema opera mais de um ativo ao mesmo tempo (ex.: WIN + WDO).
    `operacao_aberta` continua disponível por compatibilidade e traz a
    mais recente das abertas (ou null, se nenhuma).
    """
    trades_abertos = db.execute(
        select(TradeModel).where(TradeModel.aberta.is_(True)).order_by(TradeModel.timestamp_entrada.desc())
    ).scalars().all()

    def _serializar(t: TradeModel) -> dict:
        return {
            "ativo": t.ativo,
            "lado": t.lado,
            "preco_entrada": t.preco_entrada,
            "quantidade": t.quantidade,
            "timestamp_entrada": t.timestamp_entrada.isoformat(),
            "motivo_entrada": t.motivo_entrada,
            "niveis": t.niveis,
            "score_ia_entrada": t.score_ia_entrada,
            "confianca_entrada": t.confianca_entrada,
            "tempo_decorrido_minutos": round((datetime.utcnow() - t.timestamp_entrada).total_seconds() / 60, 1),
        }

    operacoes = [_serializar(t) for t in trades_abertos]

    return {
        "operacoes_abertas": operacoes,
        "operacao_aberta": operacoes[0] if operacoes else None,  # compatibilidade com versões anteriores do painel
    }


@router.get("/historico-operacoes")
def historico_operacoes(limite: int = 50, db: Session = Depends(get_db)) -> dict:
    trades = db.execute(
        select(TradeModel).order_by(TradeModel.timestamp_entrada.desc()).limit(limite)
    ).scalars().all()

    return {
        "operacoes": [
            {
                "ativo": t.ativo,
                "lado": t.lado,
                "preco_entrada": t.preco_entrada,
                "preco_saida": t.preco_saida,
                "resultado_pontos": t.resultado_pontos,
                "resultado_financeiro": t.resultado_financeiro,
                "timestamp_entrada": t.timestamp_entrada.isoformat(),
                "timestamp_saida": t.timestamp_saida.isoformat() if t.timestamp_saida else None,
                "motivo_entrada": t.motivo_entrada,
                "motivo_saida": t.motivo_saida,
                "score_ia_entrada": t.score_ia_entrada,
            }
            for t in trades
        ]
    }


def _metricas_de_resultados(resultados: list[float]) -> dict:
    if not resultados:
        return {
            "quantidade_operacoes": 0, "resultado_financeiro_total": 0.0, "win_rate": 0.0,
            "profit_factor": 0.0, "payoff": 0.0, "lucro_bruto": 0.0,
            "media_ganhos": 0.0, "media_perdas": 0.0,
        }
    ganhos = [r for r in resultados if r > 0]
    perdas = [r for r in resultados if r < 0]
    soma_ganhos = sum(ganhos)
    soma_perdas = abs(sum(perdas))
    media_ganho = (soma_ganhos / len(ganhos)) if ganhos else 0.0
    media_perda = (soma_perdas / len(perdas)) if perdas else 0.0
    profit_factor = (soma_ganhos / soma_perdas) if soma_perdas > 0 else (float("inf") if soma_ganhos > 0 else 0.0)

    return {
        "quantidade_operacoes": len(resultados),
        "resultado_financeiro_total": round(sum(resultados), 2),
        "win_rate": round(len(ganhos) / len(resultados) * 100, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
        "payoff": round(media_ganho / media_perda, 2) if media_perda > 0 else 0.0,
        "lucro_bruto": round(soma_ganhos - soma_perdas, 2),
        "media_ganhos": round(media_ganho, 2),
        "media_perdas": round(media_perda, 2),
    }


def _estatisticas_periodo(db: Session, desde: datetime) -> dict:
    trades = db.execute(
        select(TradeModel).where(TradeModel.timestamp_entrada >= desde, TradeModel.aberta.is_(False))
    ).scalars().all()
    resultados = [t.resultado_financeiro for t in trades if t.resultado_financeiro is not None]
    return _metricas_de_resultados(resultados)


@router.get("/estatisticas")
def estatisticas(db: Session = Depends(get_db)) -> dict:
    agora = datetime.utcnow()
    return {
        "diaria": _estatisticas_periodo(db, agora - timedelta(days=1)),
        "semanal": _estatisticas_periodo(db, agora - timedelta(days=7)),
        "mensal": _estatisticas_periodo(db, agora - timedelta(days=30)),
    }


@router.get("/decisoes-recentes")
def decisoes_recentes(limite: int = 20, db: Session = Depends(get_db)) -> dict:
    decisoes = db.execute(
        select(DecisaoModel).order_by(DecisaoModel.timestamp.desc()).limit(limite)
    ).scalars().all()

    return {
        "decisoes": [
            {
                "ativo": d.ativo,
                "decisao": d.decisao,
                "confianca": d.confianca,
                "score_ia": d.score_ia,
                "motivos": d.motivos,
                "timestamp": d.timestamp.isoformat(),
            }
            for d in decisoes
        ]
    }


@router.get("/diario-ia")
def diario_ia(limite: int = 50, db: Session = Depends(get_db)) -> dict:
    """O 'Diário da IA': histórico completo com Score/Confiança no momento de cada entrada."""
    return {"diario": obter_diario_ia(db, limite)}


@router.get("/evolucao-ia")
def evolucao_ia(db: Session = Depends(get_db)) -> dict:
    """
    Painel de 'Evolução da IA'. Campos sem dado real disponível (ex.:
    'último treinamento', já que nenhum modelo de ML foi treinado nesta
    etapa) vêm como null — o frontend deve exibir isso honestamente,
    não inventar um valor.
    """
    return obter_evolucao_ia(db, VERSAO_IA, INICIO_PROCESSO)


@router.get("/semaforo")
def semaforo(db: Session = Depends(get_db)) -> dict:
    """
    Semáforo do mercado: Tendência, Fluxo, Volatilidade, Liquidez e
    Horário, derivado do contexto salvo na última decisão + o status de
    pregão calculado em tempo real (o horário nunca vem de um dado
    salvo, sempre do relógio atual).
    """
    ultima = db.execute(
        select(DecisaoModel).order_by(DecisaoModel.timestamp.desc()).limit(1)
    ).scalars().first()
    pregao = obter_status_pregao()

    itens = []

    if ultima and ultima.contexto:
        ctx = ultima.contexto
        tendencia = ctx.get("tendencia")
        if tendencia in ("ALTA", "BAIXA"):
            itens.append({"dimensao": "Tendência", "status": "FAVORAVEL", "detalhe": f"Tendência de {tendencia.lower()} definida"})
        elif tendencia == "LATERAL":
            itens.append({"dimensao": "Tendência", "status": "ATENCAO", "detalhe": "Mercado sem direção definida (lateral)"})
        else:
            itens.append({"dimensao": "Tendência", "status": "ATENCAO", "detalhe": "Tendência ainda não classificada"})

        obv = ctx.get("obv")
        if obv is None:
            itens.append({"dimensao": "Fluxo", "status": "ATENCAO", "detalhe": "OBV indisponível"})
        elif abs(obv) < 1:
            itens.append({"dimensao": "Fluxo", "status": "ATENCAO", "detalhe": "Fluxo comprador/vendedor equilibrado"})
        else:
            lado = "comprador" if obv > 0 else "vendedor"
            itens.append({"dimensao": "Fluxo", "status": "FAVORAVEL", "detalhe": f"Fluxo {lado} dominante (OBV {obv:.0f})"})

        vol_map = {
            "NORMAL": ("FAVORAVEL", "Volatilidade dentro do padrão"),
            "BAIXA": ("ATENCAO", "Volatilidade baixa: movimentos podem ser insuficientes"),
            "ALTA": ("DESFAVORAVEL", "Volatilidade alta: risco de movimentos bruscos"),
        }
        status_vol, detalhe_vol = vol_map.get(ctx.get("classe_volatilidade") or "", ("ATENCAO", "Volatilidade ainda não classificada"))
        itens.append({"dimensao": "Volatilidade", "status": status_vol, "detalhe": detalhe_vol})

        vol_rel = ctx.get("volume_relativo")
        if vol_rel is None:
            itens.append({"dimensao": "Liquidez", "status": "ATENCAO", "detalhe": "Volume médio recente indisponível"})
        elif vol_rel >= 0.8:
            itens.append({"dimensao": "Liquidez", "status": "FAVORAVEL", "detalhe": f"Volume em {vol_rel:.1f}x a média recente"})
        else:
            itens.append({"dimensao": "Liquidez", "status": "DESFAVORAVEL", "detalhe": f"Volume {vol_rel:.1f}x abaixo da média recente"})
    else:
        for dimensao in ("Tendência", "Fluxo", "Volatilidade", "Liquidez"):
            itens.append({"dimensao": dimensao, "status": "ATENCAO", "detalhe": "Aguardando a primeira decisão da IA"})

    if not pregao.aberto:
        itens.append({"dimensao": "Horário", "status": "DESFAVORAVEL", "detalhe": pregao.motivo})
    elif not pregao.aceita_novas_operacoes:
        itens.append({"dimensao": "Horário", "status": "ATENCAO", "detalhe": pregao.motivo})
    else:
        itens.append({"dimensao": "Horário", "status": "FAVORAVEL", "detalhe": pregao.motivo})

    return {"semaforo": itens}


@router.get("/alertas")
def alertas(db: Session = Depends(get_db)) -> dict:
    """
    Alertas derivados do estado atual: meta/stop do dia, volatilidade,
    mercado lateral e alta probabilidade (Score alto na última decisão).
    'Conexão perdida/reconexão' depende da integração ao vivo com o
    provedor de dados (ainda não implementada) — por ora sempre reporta
    'conectado' enquanto esta API estiver respondendo.
    """
    lista = []
    agora = datetime.utcnow()

    stats_hoje = _estatisticas_periodo(db, agora - timedelta(days=1))
    if stats_hoje["resultado_financeiro_total"] >= 800:
        lista.append({"tipo": "META_ATINGIDA", "severidade": "sucesso", "mensagem": "Meta diária atingida"})
    if stats_hoje["resultado_financeiro_total"] <= -500:
        lista.append({"tipo": "STOP_ATINGIDO", "severidade": "alerta", "mensagem": "Stop diário atingido"})

    ultima_decisao = db.execute(
        select(DecisaoModel).order_by(DecisaoModel.timestamp.desc()).limit(1)
    ).scalars().first()

    if ultima_decisao:
        contexto = ultima_decisao.contexto or {}
        if contexto.get("classe_volatilidade") == "ALTA":
            lista.append({"tipo": "VOLATILIDADE_ALTA", "severidade": "atencao", "mensagem": "Mercado muito volátil"})
        if contexto.get("tendencia") == "LATERAL":
            lista.append({"tipo": "MERCADO_LATERAL", "severidade": "atencao", "mensagem": "Mercado lateral"})
        if ultima_decisao.score_ia >= 85:
            lista.append({
                "tipo": "ALTA_PROBABILIDADE",
                "severidade": "sucesso",
                "mensagem": f"Alta probabilidade encontrada (Score {ultima_decisao.score_ia:.0f}/100)",
            })

    lista.append({"tipo": "CONEXAO", "severidade": "info", "mensagem": "Conectado"})

    return {"alertas": lista}


@router.get("/resultado-operacao")
def resultado_operacao(db: Session = Depends(get_db)) -> dict:
    """
    Resultado 'em tempo real' (pontos, financeiro, percentual) de todas
    as operações abertas no momento — pode ser mais de uma quando o
    sistema opera mais de um ativo ao mesmo tempo. Usa o preço da última
    decisão registrada de cada ativo como proxy do preço atual.
    """
    resultados = obter_resultados_operacoes_abertas(db)
    return {
        "operacao_aberta": len(resultados) > 0,  # compatibilidade
        "resultados": resultados,
    }


@router.get("/performance-horario")
def performance_horario(dias: int = 30, db: Session = Depends(get_db)) -> dict:
    return {"performance": obter_performance_por_horario(db, dias)}


@router.get("/performance-dia-semana")
def performance_dia_semana(semanas: int = 8, db: Session = Depends(get_db)) -> dict:
    return {"performance": obter_performance_por_dia_semana(db, semanas)}


@router.get("/comparacao-ia-mercado")
def comparacao_ia_mercado(limite: int = 30, db: Session = Depends(get_db)) -> dict:
    return {"comparacao": obter_comparacao_ia_mercado(db, limite)}


class ConfiguracaoTradingIn(BaseModel):
    score_minimo: float | None = None
    stop_diario: float | None = None
    meta_diaria: float | None = None
    risco_por_operacao: float | None = None
    max_contratos: int | None = None
    horario_abertura: str | None = None
    horario_fechamento: str | None = None
    dias_permitidos: list[int] | None = None
    modo: str | None = None  # sempre forçado para SIMULACAO no backend, ver database.repository


@router.get("/configuracoes")
def configuracoes(db: Session = Depends(get_db)) -> dict:
    return obter_configuracoes(db)


@router.put("/configuracoes")
def atualizar_configuracoes(config: ConfiguracaoTradingIn, db: Session = Depends(get_db)) -> dict:
    atual = obter_configuracoes(db)
    novos_valores = {k: v for k, v in config.model_dump().items() if v is not None}
    atual.update(novos_valores)
    return salvar_configuracoes(db, atual)


class ConfiguracaoEstrategiaIn(BaseModel):
    quantidade_contratos: int
    alvos_pontos: list[float]
    stop_inicial_pontos: float
    inicio_trailing_pontos: float
    passo_trailing_pontos: float = 100.0


@router.get("/estrategia/{ativo}")
def config_estrategia(ativo: str, db: Session = Depends(get_db)) -> dict:
    """Contratos, alvos (pontos) e stop (pontos) do scale-out, por ativo (WIN ou WDO)."""
    from database.repository import obter_configuracao_estrategia

    return obter_configuracao_estrategia(db, ativo)


@router.put("/estrategia/{ativo}")
def atualizar_config_estrategia(ativo: str, config: ConfiguracaoEstrategiaIn, db: Session = Depends(get_db)) -> dict:
    from database.repository import salvar_configuracao_estrategia

    return salvar_configuracao_estrategia(db, ativo, config.model_dump())


class TaxaExtraCusto(BaseModel):
    nome: str
    valor: float


class CustoOperacionalIn(BaseModel):
    ativo: str
    corretora: str
    corretagem: float = 0.0
    emolumentos: float = 0.0
    registro: float = 0.0
    liquidacao: float = 0.0
    iss: float = 0.0
    outras_taxas: list[TaxaExtraCusto] = []
    data_inicio_vigencia: str | None = None
    ativo_padrao: bool = True


class CustoOperacionalUpdate(BaseModel):
    ativo: str | None = None
    corretora: str | None = None
    corretagem: float | None = None
    emolumentos: float | None = None
    registro: float | None = None
    liquidacao: float | None = None
    iss: float | None = None
    outras_taxas: list[TaxaExtraCusto] | None = None
    data_inicio_vigencia: str | None = None
    ativo_padrao: bool | None = None


class StatusCustoIn(BaseModel):
    ativo_padrao: bool


class CorretoraSelecionadaIn(BaseModel):
    corretora: str


router_custos = APIRouter(prefix="/custos-operacionais", tags=["custos-operacionais"])


@router_custos.get("")
def listar_custos(ativo: str | None = None, corretora: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    from database.repository import listar_custos_operacionais

    return listar_custos_operacionais(db, ativo, corretora)


@router_custos.get("/{custo_id}")
def obter_custo(custo_id: int, db: Session = Depends(get_db)) -> dict:
    from database.repository import obter_custo_operacional

    resultado = obter_custo_operacional(db, custo_id)
    return resultado or {"erro": "não encontrado"}


@router_custos.post("")
def criar_custo(dados: CustoOperacionalIn, db: Session = Depends(get_db)) -> dict:
    from database.repository import criar_custo_operacional

    d = dados.model_dump()
    d["outras_taxas"] = [t for t in d["outras_taxas"]]
    return criar_custo_operacional(db, d)


@router_custos.put("/{custo_id}")
def atualizar_custo(custo_id: int, dados: CustoOperacionalUpdate, db: Session = Depends(get_db)) -> dict:
    from database.repository import atualizar_custo_operacional

    d = {k: v for k, v in dados.model_dump().items() if v is not None}
    resultado = atualizar_custo_operacional(db, custo_id, d)
    return resultado or {"erro": "não encontrado"}


@router_custos.delete("/{custo_id}")
def deletar_custo(custo_id: int, db: Session = Depends(get_db)) -> dict:
    from database.repository import excluir_custo_operacional

    ok = excluir_custo_operacional(db, custo_id)
    return {"excluido": ok}


@router_custos.post("/{custo_id}/duplicar")
def duplicar_custo(custo_id: int, db: Session = Depends(get_db)) -> dict:
    from database.repository import duplicar_custo_operacional

    resultado = duplicar_custo_operacional(db, custo_id)
    return resultado or {"erro": "não encontrado"}


@router_custos.put("/{custo_id}/status")
def alternar_status_custo(custo_id: int, status: StatusCustoIn, db: Session = Depends(get_db)) -> dict:
    from database.repository import alternar_status_custo_operacional

    resultado = alternar_status_custo_operacional(db, custo_id, status.ativo_padrao)
    return resultado or {"erro": "não encontrado"}


@router_custos.get("/vigente/{ativo}")
def custo_vigente(ativo: str, corretora: str | None = None, db: Session = Depends(get_db)) -> dict:
    """O custo que está sendo usado agora pro ativo (opcionalmente, por uma corretora específica)."""
    from database.repository import obter_custo_vigente

    return obter_custo_vigente(db, ativo, corretora)


@router.get("/corretora")
def corretora_selecionada(db: Session = Depends(get_db)) -> dict:
    from database.repository import obter_corretora_selecionada

    return {"corretora": obter_corretora_selecionada(db)}


@router.put("/corretora")
def atualizar_corretora_selecionada(dados: CorretoraSelecionadaIn, db: Session = Depends(get_db)) -> dict:
    from database.repository import salvar_corretora_selecionada

    return salvar_corretora_selecionada(db, dados.corretora)


# ---------------------------------------------------------------------------
# Módulo Financeiro
# ---------------------------------------------------------------------------

class ConfiguracaoFinanceiraIn(BaseModel):
    percentual_imposto: float | None = None
    patrimonio_inicial: float | None = None


class StatusImpostoIn(BaseModel):
    pago: bool


@router_financeiro.get("/configuracao")
def obter_config_financeira(db: Session = Depends(get_db)) -> dict:
    from database.repository import obter_configuracao_financeira

    return obter_configuracao_financeira(db)


@router_financeiro.put("/configuracao")
def atualizar_config_financeira(config: ConfiguracaoFinanceiraIn, db: Session = Depends(get_db)) -> dict:
    from database.repository import obter_configuracao_financeira, salvar_configuracao_financeira

    atual = obter_configuracao_financeira(db)
    novos_valores = {k: v for k, v in config.model_dump().items() if v is not None}
    atual.update(novos_valores)
    return salvar_configuracao_financeira(db, atual)


@router_financeiro.get("/resumo")
def resumo_financeiro(
    data_inicio: str | None = None,
    data_fim: str | None = None,
    ativo: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """
    Painel Financeiro completo: lucro bruto/líquido, taxa de acerto,
    profit factor, drawdown, taxas pagas, imposto estimado, disponível.
    Filtros opcionais de período (`?data_inicio=2026-01-01&data_fim=2026-01-31`) e ativo.
    """
    from database.repository import obter_resumo_financeiro

    inicio = datetime.fromisoformat(data_inicio) if data_inicio else None
    fim = datetime.fromisoformat(data_fim) if data_fim else None
    return obter_resumo_financeiro(db, inicio, fim, ativo)


@router_financeiro.get("/mensal")
def relatorio_mensal(ano: int | None = None, db: Session = Depends(get_db)) -> dict:
    """Aba 'Impostos Mensais' — uma linha por mês do ano pedido (padrão: ano atual)."""
    from database.repository import obter_relatorio_mensal

    ano_alvo = ano or datetime.utcnow().year
    return {"ano": ano_alvo, "meses": obter_relatorio_mensal(db, ano_alvo)}


@router_financeiro.get("/anos")
def anos_disponiveis(db: Session = Depends(get_db)) -> dict:
    """Pra montar o histórico (2026, 2027, ...) — nunca apaga anos anteriores."""
    from database.repository import obter_anos_com_operacoes

    return {"anos": obter_anos_com_operacoes(db)}


@router_financeiro.put("/mensal/{ano}/{mes}/status")
def atualizar_status_mensal(ano: int, mes: int, status: StatusImpostoIn, db: Session = Depends(get_db)) -> dict:
    from database.repository import marcar_status_imposto_mensal

    if not 1 <= mes <= 12:
        return {"erro": "mês inválido, use 1-12"}
    return marcar_status_imposto_mensal(db, ano, mes, status.pago)


@router_financeiro.get("/dashboard")
def dashboard_financeiro(db: Session = Depends(get_db)) -> dict:
    """Lucro hoje/semana/mês/ano, patrimônio atual, evolução, drawdown, maior gain/loss."""
    from database.repository import obter_dashboard_financeiro

    return obter_dashboard_financeiro(db)


@router_financeiro.get("/relatorio.csv")
def relatorio_csv(
    data_inicio: str | None = None,
    data_fim: str | None = None,
    ativo: str | None = None,
    db: Session = Depends(get_db),
):
    """Exporta as operações do período em CSV (Excel abre normalmente)."""
    import csv
    import io

    from fastapi.responses import StreamingResponse

    from database.repository import _custos_por_ativo_de_trades, _trades_fechados_no_periodo, obter_configuracao_financeira
    from financeiro.calculo import calcular_resultado_operacao

    inicio = datetime.fromisoformat(data_inicio) if data_inicio else None
    fim = datetime.fromisoformat(data_fim) if data_fim else None
    config = obter_configuracao_financeira(db)
    trades = _trades_fechados_no_periodo(db, inicio, fim, ativo)
    custos_por_ativo = _custos_por_ativo_de_trades(db, trades)

    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";")
    escritor.writerow([
        "Ativo", "Entrada", "Saída", "Quantidade", "Pontos",
        "Lucro Bruto (R$)", "Custos (R$)", "Lucro Líquido (R$)",
    ])
    for t in trades:
        if t.resultado_pontos is None:
            continue
        r = calcular_resultado_operacao(t, config, custos_por_ativo)
        escritor.writerow([
            r.ativo,
            r.timestamp_entrada.strftime("%d/%m/%Y %H:%M:%S"),
            r.timestamp_saida.strftime("%d/%m/%Y %H:%M:%S") if r.timestamp_saida else "",
            r.quantidade,
            r.resultado_pontos,
            f"{r.lucro_bruto:.2f}".replace(".", ","),
            f"{r.custos:.2f}".replace(".", ","),
            f"{r.lucro_liquido:.2f}".replace(".", ","),
        ])

    buffer.seek(0)
    nome_arquivo = f"relatorio_tmp10_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={nome_arquivo}"},
    )
