"""
Repositório — ponte entre as entidades de domínio (core/entities.py) e as
tabelas do banco (database/models.py).

Isso existe para que `simulation/` e `backtest/` nunca precisem importar
SQLAlchemy diretamente — eles continuam puros, e quem quiser persistir
(um "runner" ao vivo, por exemplo) passa estas funções como callbacks
(`ao_decidir`, `ao_fechar_ordem`) para o `SimuladorPaperTrading`.
"""

from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.entities import DecisaoTrade, OrdemSimulada
from database.models import (
    ConfiguracaoModel,
    CustoOperacionalModel,
    DecisaoModel,
    ImpostoMensalModel,
    TradeModel,
)
from financeiro.configuracao import CHAVE_CONFIG_FINANCEIRA, CONFIG_FINANCEIRA_PADRAO
from market.instrumentos import obter_valor_por_ponto

CHAVE_CONFIG_TRADING = "config_trading"

CONFIG_PADRAO = {
    "score_minimo": 70.0,
    "stop_diario": 500.0,
    "meta_diaria": 800.0,
    "risco_por_operacao": 100.0,
    "max_contratos": 1,
    "horario_abertura": "09:00",
    "horario_fechamento": "17:45",
    "dias_permitidos": [0, 1, 2, 3, 4],  # 0=segunda ... 6=domingo
    "modo": "SIMULACAO",  # "REAL" não é uma opção funcional nesta etapa
}


def _contexto_para_dict(decisao: DecisaoTrade) -> dict:
    ctx = decisao.contexto
    return {
        "tendencia": ctx.tendencia,
        "reversao_detectada": ctx.reversao_detectada,
        "padroes_detectados": ctx.padroes_detectados,
        "classe_volatilidade": ctx.classe_volatilidade,
        "volume_relativo": ctx.volume_relativo,
        "obv": ctx.indicadores.obv,
        "preco": ctx.candle_atual.fechamento,
    }


def salvar_decisao(db: Session, decisao: DecisaoTrade) -> DecisaoModel:
    registro = DecisaoModel(
        ativo=decisao.contexto.ativo,
        timestamp=decisao.timestamp,
        decisao=decisao.decisao.value,
        confianca=decisao.confianca,
        motivos=decisao.motivos,
        contexto=_contexto_para_dict(decisao),
        score_ia=decisao.score_ia,
        fatores=decisao.fatores,
        explicacao=decisao.explicacao,
        checklist=[asdict(item) for item in decisao.checklist],
        atividade_ia=decisao.atividade_ia,
    )
    db.add(registro)
    db.commit()
    return registro


def salvar_ordem_aberta(db: Session, ordem: OrdemSimulada, origem: str = "SIMULACAO") -> TradeModel:
    registro = TradeModel(
        ativo=ordem.ativo,
        origem=origem,
        lado=ordem.lado.value,
        preco_entrada=ordem.preco_entrada,
        quantidade=ordem.quantidade,
        timestamp_entrada=ordem.timestamp_entrada,
        motivo_entrada=ordem.motivo_entrada,
        aberta=True,
        niveis=asdict(ordem.niveis) if ordem.niveis else None,
        score_ia_entrada=ordem.score_ia_entrada,
        confianca_entrada=ordem.confianca_entrada,
        grupo_entrada_id=ordem.grupo_entrada_id,
        alvo_pontos=ordem.alvo_pontos,
    )
    db.add(registro)
    db.commit()
    return registro


def atualizar_ordem_fechada(db: Session, ordem: OrdemSimulada) -> TradeModel | None:
    """
    Encontra a ordem aberta correspondente e a fecha.

    Quando a entrada usa scale-out (`grupo_entrada_id` preenchido), o
    contrato certo é identificado por grupo + alvo (cada contrato do
    mesmo grupo tem um alvo diferente, ou None para o "corredor") —
    isso é NECESSÁRIO porque vários contratos do mesmo grupo têm o
    mesmo ativo e o mesmo horário de entrada, então esses dois campos
    sozinhos não seriam suficientes pra achar o registro certo.
    """
    if ordem.grupo_entrada_id:
        filtro = [
            TradeModel.grupo_entrada_id == ordem.grupo_entrada_id,
            TradeModel.alvo_pontos == ordem.alvo_pontos,
            TradeModel.aberta.is_(True),
        ]
    else:
        filtro = [
            TradeModel.ativo == ordem.ativo,
            TradeModel.timestamp_entrada == ordem.timestamp_entrada,
            TradeModel.aberta.is_(True),
        ]

    registro = db.execute(
        select(TradeModel).where(*filtro).order_by(TradeModel.id.desc())
    ).scalars().first()

    if registro is None:
        return None

    registro.preco_saida = ordem.preco_saida
    registro.timestamp_saida = ordem.timestamp_saida
    registro.motivo_saida = ordem.motivo_saida
    registro.resultado_pontos = ordem.resultado_pontos
    registro.resultado_financeiro = ordem.resultado_financeiro
    registro.aberta = False
    db.commit()
    return registro


def obter_evolucao_ia(db: Session, versao_ia: str, inicio_processo: datetime) -> dict:
    """Estatísticas de 'Evolução da IA' — apenas dados que realmente existem no banco."""
    total_decisoes = db.execute(select(func.count()).select_from(DecisaoModel)).scalar() or 0
    total_trades_fechados = db.execute(
        select(func.count()).select_from(TradeModel).where(TradeModel.aberta.is_(False))
    ).scalar() or 0

    decisoes_com_padroes = db.execute(
        select(DecisaoModel.contexto).where(DecisaoModel.contexto.isnot(None))
    ).scalars().all()
    padroes_unicos: set[str] = set()
    for ctx in decisoes_com_padroes:
        for p in (ctx or {}).get("padroes_detectados", []):
            padroes_unicos.add(p)

    trades_fechados = db.execute(
        select(TradeModel.resultado_financeiro).where(TradeModel.aberta.is_(False))
    ).scalars().all()
    resultados = [r for r in trades_fechados if r is not None]
    precisao_simulacao = (
        round(len([r for r in resultados if r > 0]) / len(resultados) * 100, 1) if resultados else None
    )

    tempo_online = datetime.utcnow() - inicio_processo

    return {
        "operacoes_analisadas": total_decisoes,
        "operacoes_fechadas": total_trades_fechados,
        "padroes_identificados": sorted(padroes_unicos),
        "precisao_backtest": None,  # depende de backtests salvos — ver tabela `backtests`
        "precisao_simulacao": precisao_simulacao,
        "ultimo_treinamento": None,  # nenhum modelo de ML foi treinado nesta etapa
        "versao_ia": versao_ia,
        "tempo_online_segundos": int(tempo_online.total_seconds()),
    }


def obter_diario_ia(db: Session, limite: int = 50) -> list[dict]:
    """
    Une decisões e trades por proximidade de horário/ativo para montar o
    'Diário da IA': cada operação, com o Score e a Confiança que a IA
    tinha no momento da entrada.
    """
    trades = db.execute(
        select(TradeModel).order_by(TradeModel.timestamp_entrada.desc()).limit(limite)
    ).scalars().all()

    diario = []
    for t in trades:
        diario.append(
            {
                "data": t.timestamp_entrada.date().isoformat(),
                "hora": t.timestamp_entrada.time().isoformat(timespec="seconds"),
                "lado": t.lado,
                "preco_entrada": t.preco_entrada,
                "preco_saida": t.preco_saida,
                "motivo_entrada": t.motivo_entrada,
                "motivo_saida": t.motivo_saida,
                "resultado_pontos": t.resultado_pontos,
                "resultado_financeiro": t.resultado_financeiro,
                "tempo_operacao_minutos": (
                    round((t.timestamp_saida - t.timestamp_entrada).total_seconds() / 60, 1)
                    if t.timestamp_saida
                    else None
                ),
                "score_ia_entrada": t.score_ia_entrada,
                "confianca_entrada": t.confianca_entrada,
            }
        )
    return diario


def obter_configuracoes(db: Session) -> dict:
    """Retorna a configuração persistida, ou os padrões se nunca foi salva."""
    registro = db.execute(
        select(ConfiguracaoModel).where(ConfiguracaoModel.chave == CHAVE_CONFIG_TRADING)
    ).scalars().first()
    if registro is None:
        return dict(CONFIG_PADRAO)
    config = dict(CONFIG_PADRAO)
    config.update(registro.valor or {})
    config["modo"] = "SIMULACAO"  # trava: modo real não é habilitado por configuração nesta etapa
    return config


def salvar_configuracoes(db: Session, config: dict) -> dict:
    """
    Salva a configuração. `modo` é sempre forçado para 'SIMULACAO' — não
    existe envio de ordens reais implementado nesta etapa, então a opção
    'REAL' nunca é persistida como ativa, mesmo que enviada pelo painel.
    """
    config_segura = dict(config)
    config_segura["modo"] = "SIMULACAO"

    registro = db.execute(
        select(ConfiguracaoModel).where(ConfiguracaoModel.chave == CHAVE_CONFIG_TRADING)
    ).scalars().first()

    if registro is None:
        registro = ConfiguracaoModel(chave=CHAVE_CONFIG_TRADING, valor=config_segura)
        db.add(registro)
    else:
        registro.valor = config_segura

    db.commit()
    return obter_configuracoes(db)


def obter_performance_por_horario(db: Session, dias: int = 30) -> list[dict]:
    """Agrupa os trades fechados por hora de entrada (8h-17h), para achar os melhores horários."""
    desde = datetime.utcnow() - timedelta(days=dias)
    trades = db.execute(
        select(TradeModel).where(TradeModel.timestamp_entrada >= desde, TradeModel.aberta.is_(False))
    ).scalars().all()

    por_hora: dict[int, list[float]] = {h: [] for h in range(8, 18)}
    for t in trades:
        hora = t.timestamp_entrada.hour
        if hora in por_hora and t.resultado_financeiro is not None:
            por_hora[hora].append(t.resultado_financeiro)

    resultado = []
    for hora, resultados in por_hora.items():
        ganhos = [r for r in resultados if r > 0]
        resultado.append(
            {
                "hora": f"{hora:02d}h",
                "lucro": round(sum(resultados), 2),
                "quantidade_trades": len(resultados),
                "win_rate": round(len(ganhos) / len(resultados) * 100, 1) if resultados else 0.0,
            }
        )
    return resultado


def obter_performance_por_dia_semana(db: Session, semanas: int = 8) -> list[dict]:
    """Agrupa os trades fechados por dia da semana (segunda a sexta)."""
    desde = datetime.utcnow() - timedelta(weeks=semanas)
    trades = db.execute(
        select(TradeModel).where(TradeModel.timestamp_entrada >= desde, TradeModel.aberta.is_(False))
    ).scalars().all()

    nomes = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta"]
    por_dia: dict[int, list[float]] = {d: [] for d in range(5)}
    for t in trades:
        dia = t.timestamp_entrada.weekday()
        if dia in por_dia and t.resultado_financeiro is not None:
            por_dia[dia].append(t.resultado_financeiro)

    resultado = []
    for dia, resultados in por_dia.items():
        ganhos = [r for r in resultados if r > 0]
        perdas = [r for r in resultados if r < 0]
        capital = 0.0
        pico = 0.0
        drawdown_maximo = 0.0
        for r in resultados:
            capital += r
            pico = max(pico, capital)
            drawdown_maximo = max(drawdown_maximo, pico - capital)
        resultado.append(
            {
                "dia": nomes[dia],
                "lucro": round(sum(ganhos), 2),
                "perda": round(sum(perdas), 2),
                "win_rate": round(len(ganhos) / len(resultados) * 100, 1) if resultados else 0.0,
                "drawdown": round(drawdown_maximo, 2),
            }
        )
    return resultado


def _motivo_desvio(motivo_saida: str | None, acertou: bool) -> str:
    if acertou or not motivo_saida:
        return ""
    motivo_lower = motivo_saida.lower()
    if "lateral" in motivo_lower:
        return "Mercado perdeu força e entrou em lateralização antes de confirmar o movimento esperado"
    if "pregão" in motivo_lower or "horário" in motivo_lower:
        return "Operação encerrada por horário antes do movimento se concretizar"
    if "reversão" in motivo_lower or "reversao" in motivo_lower:
        return "Sinal de reversão surgiu antes do alvo, invalidando a tese original"
    return "Sinal oposto surgiu antes do movimento esperado se confirmar"


def obter_comparacao_ia_mercado(db: Session, limite: int = 30) -> list[dict]:
    """
    'O que a IA esperava' (direção + motivo da entrada) vs 'o que
    realmente aconteceu' (resultado do trade), para auditoria e
    aprendizado futuro — é a base para qualquer treinamento posterior.
    """
    trades = db.execute(
        select(TradeModel)
        .where(TradeModel.aberta.is_(False))
        .order_by(TradeModel.timestamp_entrada.desc())
        .limit(limite)
    ).scalars().all()

    comparacao = []
    for t in trades:
        acertou = (t.resultado_financeiro or 0) > 0
        pontos_txt = f" ({t.resultado_pontos:+.0f} pontos)" if t.resultado_pontos is not None else ""
        comparacao.append(
            {
                "timestamp": t.timestamp_entrada.isoformat(),
                "esperado": f"{t.lado} — {t.motivo_entrada}",
                "resultado_real": (
                    f"{'Lucro' if acertou else 'Perda'} de {formatar_valor(t.resultado_financeiro)}{pontos_txt}"
                ),
                "acertou": acertou,
                "motivo_desvio": _motivo_desvio(t.motivo_saida, acertou),
                "score_ia_entrada": t.score_ia_entrada,
            }
        )
    return comparacao


def formatar_valor(valor: float | None) -> str:
    if valor is None:
        return "R$ 0,00"
    return f"R$ {abs(valor):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def obter_resultados_operacoes_abertas(db: Session) -> list[dict]:
    """
    Resultado "em tempo real" de TODAS as operações abertas no momento —
    o sistema pode ter mais de uma posição aberta ao mesmo tempo quando
    opera mais de um ativo (ex.: WIN e WDO simultaneamente, ver
    `simulation/orquestrador.py`). Cada item usa o preço da última
    decisão registrada PARA AQUELE ATIVO como proxy do preço atual.
    """
    trades_abertos = db.execute(
        select(TradeModel).where(TradeModel.aberta.is_(True)).order_by(TradeModel.timestamp_entrada.desc())
    ).scalars().all()

    resultados = []
    for trade_aberto in trades_abertos:
        ultima_decisao = db.execute(
            select(DecisaoModel)
            .where(DecisaoModel.ativo == trade_aberto.ativo)
            .order_by(DecisaoModel.timestamp.desc())
        ).scalars().first()

        if ultima_decisao is None or not ultima_decisao.contexto or "preco" not in ultima_decisao.contexto:
            resultados.append({"ativo": trade_aberto.ativo, "preco_atual": None, "disponivel": False})
            continue

        preco_atual = ultima_decisao.contexto["preco"]
        sinal = 1 if trade_aberto.lado == "COMPRA" else -1
        pontos = (preco_atual - trade_aberto.preco_entrada) * sinal
        financeiro = pontos * obter_valor_por_ponto(trade_aberto.ativo) * trade_aberto.quantidade
        percentual = (pontos / trade_aberto.preco_entrada) * 100 if trade_aberto.preco_entrada else 0.0

        resultados.append({
            "ativo": trade_aberto.ativo,
            "disponivel": True,
            "preco_atual": preco_atual,
            "pontos": round(pontos, 2),
            "financeiro": round(financeiro, 2),
            "percentual": round(percentual, 3),
            "atualizado_em": ultima_decisao.timestamp.isoformat(),
        })

    return resultados


# ---------------------------------------------------------------------------
# Módulo Financeiro — configuração, resumo, relatório mensal, dashboard
# ---------------------------------------------------------------------------

def obter_configuracao_financeira(db: Session) -> dict:
    """Retorna a configuração financeira persistida, ou os padrões se nunca foi salva."""
    registro = db.execute(
        select(ConfiguracaoModel).where(ConfiguracaoModel.chave == CHAVE_CONFIG_FINANCEIRA)
    ).scalars().first()
    config = dict(CONFIG_FINANCEIRA_PADRAO)
    if registro is not None:
        config.update(registro.valor or {})
    return config


def salvar_configuracao_financeira(db: Session, config: dict) -> dict:
    """
    Salva a configuração financeira. Nenhuma validação de negócio além do
    básico (tipos) — o usuário pode ajustar qualquer taxa livremente,
    como pedido: 'nenhum valor poderá ficar fixo no código'.
    """
    config_final = dict(CONFIG_FINANCEIRA_PADRAO)
    config_final.update(config)

    registro = db.execute(
        select(ConfiguracaoModel).where(ConfiguracaoModel.chave == CHAVE_CONFIG_FINANCEIRA)
    ).scalars().first()

    if registro is None:
        registro = ConfiguracaoModel(chave=CHAVE_CONFIG_FINANCEIRA, valor=config_final)
        db.add(registro)
    else:
        registro.valor = config_final

    db.commit()
    return config_final


def _trades_fechados_no_periodo(
    db: Session, data_inicio: datetime | None = None, data_fim: datetime | None = None, ativo: str | None = None
) -> list[TradeModel]:
    filtros = [TradeModel.aberta.is_(False)]
    if data_inicio is not None:
        filtros.append(TradeModel.timestamp_saida >= data_inicio)
    if data_fim is not None:
        filtros.append(TradeModel.timestamp_saida <= data_fim)
    if ativo is not None:
        filtros.append(TradeModel.ativo == ativo)
    return db.execute(select(TradeModel).where(*filtros)).scalars().all()


def _custos_por_ativo_de_trades(db: Session, trades: list) -> dict[str, float]:
    """Busca, em custos_operacionais, a Taxa Total por Contrato vigente pra cada ativo distinto na lista de trades."""
    ativos = {t.ativo.upper() for t in trades}
    return {ativo: obter_custo_vigente(db, ativo)["taxa_total_contrato"] for ativo in ativos}


def obter_resumo_financeiro(
    db: Session, data_inicio: datetime | None = None, data_fim: datetime | None = None, ativo: str | None = None
) -> dict:
    """O Painel Financeiro — sempre calculado na hora, com a configuração e os custos ATUAIS."""
    from financeiro.calculo import calcular_resumo

    config = obter_configuracao_financeira(db)
    trades = _trades_fechados_no_periodo(db, data_inicio, data_fim, ativo)
    custos_por_ativo = _custos_por_ativo_de_trades(db, trades)
    return asdict(calcular_resumo(trades, config, custos_por_ativo))


def obter_relatorio_mensal(db: Session, ano: int) -> list[dict]:
    """Uma linha por mês do ano pedido, com o status Pago/Pendente salvo no banco."""
    from financeiro.calculo import calcular_resumo

    config = obter_configuracao_financeira(db)
    nomes_meses = [
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
    ]

    status_salvos = {
        r.mes: r.pago
        for r in db.execute(select(ImpostoMensalModel).where(ImpostoMensalModel.ano == ano)).scalars().all()
    }

    linhas = []
    for mes in range(1, 13):
        inicio = datetime(ano, mes, 1)
        fim = datetime(ano + 1, 1, 1) if mes == 12 else datetime(ano, mes + 1, 1)
        trades = _trades_fechados_no_periodo(db, inicio, fim)
        custos_por_ativo = _custos_por_ativo_de_trades(db, trades)
        resumo = calcular_resumo(trades, config, custos_por_ativo)
        linhas.append({
            "ano": ano,
            "mes": mes,
            "nome_mes": nomes_meses[mes - 1],
            "lucro_bruto": resumo.lucro_bruto,
            "prejuizo_bruto": resumo.prejuizo_bruto,
            "total_taxas_pagas": resumo.total_taxas_pagas,
            "lucro_liquido": resumo.lucro_liquido,
            "imposto_estimado": resumo.imposto_estimado,
            "total_operacoes": resumo.total_operacoes,
            "pago": status_salvos.get(mes, False),
        })
    return linhas


def obter_anos_com_operacoes(db: Session) -> list[int]:
    """Todos os anos que têm pelo menos 1 operação fechada — pra montar o histórico (nunca apaga nada)."""
    trades = db.execute(
        select(TradeModel.timestamp_saida).where(TradeModel.aberta.is_(False))
    ).scalars().all()
    anos = sorted({t.year for t in trades if t is not None}, reverse=True)
    return anos or [datetime.utcnow().year]


def marcar_status_imposto_mensal(db: Session, ano: int, mes: int, pago: bool) -> dict:
    registro = db.execute(
        select(ImpostoMensalModel).where(ImpostoMensalModel.ano == ano, ImpostoMensalModel.mes == mes)
    ).scalars().first()

    if registro is None:
        registro = ImpostoMensalModel(ano=ano, mes=mes, pago=pago)
        db.add(registro)
    else:
        registro.pago = pago

    db.commit()
    return {"ano": ano, "mes": mes, "pago": pago}


def obter_dashboard_financeiro(db: Session) -> dict:
    """Painel geral: lucro hoje/semana/mês/ano, patrimônio, evolução."""
    from financeiro.calculo import calcular_resultado_operacao, calcular_resumo

    config = obter_configuracao_financeira(db)
    agora = datetime.utcnow()
    hoje_inicio = datetime(agora.year, agora.month, agora.day)
    semana_inicio = hoje_inicio - timedelta(days=hoje_inicio.weekday())
    mes_inicio = datetime(agora.year, agora.month, 1)
    ano_inicio = datetime(agora.year, 1, 1)

    todos_trades = _trades_fechados_no_periodo(db, None, None)
    custos_por_ativo = _custos_por_ativo_de_trades(db, todos_trades)

    def lucro_desde(inicio: datetime) -> float:
        trades = _trades_fechados_no_periodo(db, inicio, None)
        return calcular_resumo(trades, config, custos_por_ativo).lucro_liquido

    resumo_geral = calcular_resumo(todos_trades, config, custos_por_ativo)

    patrimonio_inicial = config.get("patrimonio_inicial", 0.0)
    patrimonio_atual = patrimonio_inicial + resumo_geral.lucro_liquido

    # evolução do patrimônio — 1 ponto por operação fechada
    trades_ordenados = sorted(
        [t for t in todos_trades if t.resultado_pontos is not None],
        key=lambda t: t.timestamp_saida or t.timestamp_entrada,
    )
    evolucao = []
    acumulado = patrimonio_inicial
    for t in trades_ordenados:
        resultado = calcular_resultado_operacao(t, config, custos_por_ativo)
        acumulado += resultado.lucro_liquido
        evolucao.append({
            "timestamp": (t.timestamp_saida or t.timestamp_entrada).isoformat(),
            "patrimonio": round(acumulado, 2),
        })

    return {
        "lucro_hoje": round(lucro_desde(hoje_inicio), 2),
        "lucro_semana": round(lucro_desde(semana_inicio), 2),
        "lucro_mes": round(lucro_desde(mes_inicio), 2),
        "lucro_ano": round(lucro_desde(ano_inicio), 2),
        "total_taxas": resumo_geral.total_taxas_pagas,
        "total_impostos": resumo_geral.imposto_estimado,
        "valor_disponivel": resumo_geral.lucro_disponivel,
        "drawdown_maximo": resumo_geral.drawdown_maximo,
        "maior_gain": resumo_geral.maior_gain,
        "maior_loss": resumo_geral.maior_loss,
        "patrimonio_inicial": patrimonio_inicial,
        "patrimonio_atual": round(patrimonio_atual, 2),
        "rentabilidade_percentual": (
            round((resumo_geral.lucro_liquido / patrimonio_inicial) * 100, 2) if patrimonio_inicial else None
        ),
        "evolucao_patrimonio": evolucao,
    }


# ---------------------------------------------------------------------------
# Configuração de Estratégia (contratos, alvos e stop em pontos, por ativo)
# ---------------------------------------------------------------------------

def _chave_config_estrategia(ativo: str) -> str:
    return f"config_estrategia_{ativo.upper()}"


def obter_configuracao_estrategia(db: Session, ativo: str) -> dict:
    """
    Retorna a configuração de scale-out (contratos, alvos em pontos, stop
    em pontos, trailing) para o ativo pedido — a que estiver salva no
    banco, ou os valores padrão validados (orders/scale_out.py) se nunca
    foi editada pelo usuário.
    """
    from orders.scale_out import CONFIGURACOES_SCALE_OUT, config_scale_out_para_dict

    registro = db.execute(
        select(ConfiguracaoModel).where(ConfiguracaoModel.chave == _chave_config_estrategia(ativo))
    ).scalars().first()

    if registro is not None:
        return registro.valor

    padrao = CONFIGURACOES_SCALE_OUT.get(ativo.upper())
    if padrao is None:
        return {
            "quantidade_contratos": 1,
            "alvos_pontos": [150, 200, 350],
            "stop_inicial_pontos": 150,
            "inicio_trailing_pontos": 250,
            "passo_trailing_pontos": 100,
        }
    return config_scale_out_para_dict(padrao)


def salvar_configuracao_estrategia(db: Session, ativo: str, config: dict) -> dict:
    chave = _chave_config_estrategia(ativo)
    registro = db.execute(
        select(ConfiguracaoModel).where(ConfiguracaoModel.chave == chave)
    ).scalars().first()

    if registro is None:
        registro = ConfiguracaoModel(chave=chave, valor=config)
        db.add(registro)
    else:
        registro.valor = config

    db.commit()
    return config


# ---------------------------------------------------------------------------
# Custos Operacionais (corretagem, emolumentos, registro, liquidação, ISS,
# outras taxas) — configuráveis por ativo + corretora, SUBSTITUEM
# qualquer taxa fixa no código.
# ---------------------------------------------------------------------------

def _custo_para_dict(c: CustoOperacionalModel) -> dict:
    return {
        "id": c.id,
        "ativo": c.ativo,
        "corretora": c.corretora,
        "corretagem": c.corretagem,
        "emolumentos": c.emolumentos,
        "registro": c.registro,
        "liquidacao": c.liquidacao,
        "iss": c.iss,
        "outras_taxas": c.outras_taxas or [],
        "taxa_total_contrato": c.taxa_total_contrato,
        "data_inicio_vigencia": c.data_inicio_vigencia.isoformat() if c.data_inicio_vigencia else None,
        "ativo_padrao": c.ativo_padrao,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def listar_custos_operacionais(
    db: Session, ativo: str | None = None, corretora: str | None = None
) -> list[dict]:
    filtros = []
    if ativo:
        filtros.append(CustoOperacionalModel.ativo == ativo.upper())
    if corretora:
        filtros.append(CustoOperacionalModel.corretora == corretora)
    registros = db.execute(
        select(CustoOperacionalModel).where(*filtros).order_by(CustoOperacionalModel.ativo, CustoOperacionalModel.corretora)
    ).scalars().all()
    return [_custo_para_dict(c) for c in registros]


def obter_custo_operacional(db: Session, custo_id: int) -> dict | None:
    registro = db.get(CustoOperacionalModel, custo_id)
    return _custo_para_dict(registro) if registro else None


def criar_custo_operacional(db: Session, dados: dict) -> dict:
    from custos.calculo import calcular_taxa_total

    taxa_total = calcular_taxa_total(
        dados.get("corretagem", 0.0), dados.get("emolumentos", 0.0), dados.get("registro", 0.0),
        dados.get("liquidacao", 0.0), dados.get("iss", 0.0), dados.get("outras_taxas", []),
    )
    registro = CustoOperacionalModel(
        ativo=dados["ativo"].upper(),
        corretora=dados["corretora"],
        corretagem=dados.get("corretagem", 0.0),
        emolumentos=dados.get("emolumentos", 0.0),
        registro=dados.get("registro", 0.0),
        liquidacao=dados.get("liquidacao", 0.0),
        iss=dados.get("iss", 0.0),
        outras_taxas=dados.get("outras_taxas", []),
        taxa_total_contrato=taxa_total,
        data_inicio_vigencia=(
            datetime.fromisoformat(dados["data_inicio_vigencia"]) if dados.get("data_inicio_vigencia") else datetime.utcnow()
        ),
        ativo_padrao=dados.get("ativo_padrao", True),
    )
    db.add(registro)
    db.commit()
    return _custo_para_dict(registro)


def atualizar_custo_operacional(db: Session, custo_id: int, dados: dict) -> dict | None:
    from custos.calculo import calcular_taxa_total

    registro = db.get(CustoOperacionalModel, custo_id)
    if registro is None:
        return None

    for campo in ("corretagem", "emolumentos", "registro", "liquidacao", "iss", "outras_taxas", "ativo_padrao"):
        if campo in dados:
            setattr(registro, campo, dados[campo])
    if "ativo" in dados:
        registro.ativo = dados["ativo"].upper()
    if "corretora" in dados:
        registro.corretora = dados["corretora"]
    if "data_inicio_vigencia" in dados and dados["data_inicio_vigencia"]:
        registro.data_inicio_vigencia = datetime.fromisoformat(dados["data_inicio_vigencia"])

    registro.taxa_total_contrato = calcular_taxa_total(
        registro.corretagem, registro.emolumentos, registro.registro,
        registro.liquidacao, registro.iss, registro.outras_taxas,
    )
    db.commit()
    return _custo_para_dict(registro)


def excluir_custo_operacional(db: Session, custo_id: int) -> bool:
    registro = db.get(CustoOperacionalModel, custo_id)
    if registro is None:
        return False
    db.delete(registro)
    db.commit()
    return True


def duplicar_custo_operacional(db: Session, custo_id: int) -> dict | None:
    original = db.get(CustoOperacionalModel, custo_id)
    if original is None:
        return None
    copia = CustoOperacionalModel(
        ativo=original.ativo,
        corretora=original.corretora,
        corretagem=original.corretagem,
        emolumentos=original.emolumentos,
        registro=original.registro,
        liquidacao=original.liquidacao,
        iss=original.iss,
        outras_taxas=original.outras_taxas,
        taxa_total_contrato=original.taxa_total_contrato,
        data_inicio_vigencia=datetime.utcnow(),
        ativo_padrao=False,  # cópia começa inativa, pra não conflitar com o original vigente
    )
    db.add(copia)
    db.commit()
    return _custo_para_dict(copia)


def alternar_status_custo_operacional(db: Session, custo_id: int, ativo_padrao: bool) -> dict | None:
    registro = db.get(CustoOperacionalModel, custo_id)
    if registro is None:
        return None
    registro.ativo_padrao = ativo_padrao
    db.commit()
    return _custo_para_dict(registro)


def obter_custo_vigente(db: Session, ativo: str, corretora: str | None = None) -> dict:
    """
    Retorna o custo operacional VIGENTE (ativo_padrao=True, com a
    data_inicio_vigencia mais recente que já passou) para o ativo (e,
    se informada, a corretora — senão usa a corretora selecionada nas
    configurações). Se nada estiver cadastrado, devolve zerado (nunca
    inventa um valor fixo).

    Casa por PREFIXO (não por igualdade exata), porque contratos futuros
    vêm com sufixo de vencimento no código real (ex.: 'WINQ26'), mas o
    cadastro de custo é feito pelo ativo-base (ex.: 'WIN') — do mesmo
    jeito que já funciona em market.instrumentos.obter_valor_por_ponto.
    """
    if corretora is None:
        corretora = obter_corretora_selecionada(db)

    ativo_upper = (ativo or "").upper()
    agora = datetime.utcnow()
    filtros = [
        CustoOperacionalModel.ativo_padrao.is_(True),
        CustoOperacionalModel.data_inicio_vigencia <= agora,
    ]
    if corretora:
        filtros.append(CustoOperacionalModel.corretora == corretora)

    candidatos = db.execute(
        select(CustoOperacionalModel).where(*filtros).order_by(CustoOperacionalModel.data_inicio_vigencia.desc())
    ).scalars().all()

    registro = next((c for c in candidatos if ativo_upper.startswith(c.ativo.upper())), None)

    if registro is None:
        return {
            "ativo": ativo_upper, "corretora": corretora, "corretagem": 0.0, "emolumentos": 0.0,
            "registro": 0.0, "liquidacao": 0.0, "iss": 0.0, "outras_taxas": [],
            "taxa_total_contrato": 0.0, "encontrado": False,
        }
    d = _custo_para_dict(registro)
    d["encontrado"] = True
    return d


CHAVE_CORRETORA_SELECIONADA = "corretora_selecionada"


def obter_corretora_selecionada(db: Session) -> str | None:
    registro = db.execute(
        select(ConfiguracaoModel).where(ConfiguracaoModel.chave == CHAVE_CORRETORA_SELECIONADA)
    ).scalars().first()
    return registro.valor.get("corretora") if registro else None


def salvar_corretora_selecionada(db: Session, corretora: str) -> dict:
    registro = db.execute(
        select(ConfiguracaoModel).where(ConfiguracaoModel.chave == CHAVE_CORRETORA_SELECIONADA)
    ).scalars().first()
    if registro is None:
        registro = ConfiguracaoModel(chave=CHAVE_CORRETORA_SELECIONADA, valor={"corretora": corretora})
        db.add(registro)
    else:
        registro.valor = {"corretora": corretora}
    db.commit()
    return {"corretora": corretora}
