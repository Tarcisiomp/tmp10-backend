"""
Geração de linguagem natural: a explicação "por que a IA decidiu operar"
e o rótulo de "o que a IA está fazendo agora".

Isso existe porque o objetivo do projeto não é só cuspir COMPRAR/VENDER —
é permitir que o operador humano acompanhe e avalie o raciocínio. Nenhuma
das frases aqui é gerada por um LLM: é composição de texto a partir dos
mesmos fatores que já alimentam o score, então a explicação é sempre
rastreável e nunca "inventa" um motivo que não influenciou a decisão.
"""

from core.entities import ContextoMercado, Decisao


def gerar_explicacao(contexto: ContextoMercado, decisao: Decisao, motivos: list[str], score_ia: float) -> str:
    if decisao == Decisao.AGUARDAR:
        if not motivos:
            return "A IA optou por aguardar: nenhum sinal relevante foi identificado neste momento."
        return (
            "A IA optou por aguardar em vez de operar. "
            + " ".join(motivos)
            + f" Com esses sinais, o Score da IA ficou em {score_ia:.0f}/100 — "
            "abaixo do necessário para justificar uma entrada."
        )

    verbo = "comprada" if decisao == Decisao.COMPRAR else "vendida"
    ativo = contexto.ativo
    tf = contexto.timeframe.value if hasattr(contexto.timeframe, "value") else contexto.timeframe

    corpo = (
        f"A IA entrou {verbo} em {ativo} no gráfico de {tf} porque identificou "
        + "; ".join(motivos).lower()
        + f". O Score da IA para esta decisão foi de {score_ia:.0f}/100."
    )
    return corpo[0].upper() + corpo[1:]


def gerar_atividade_ia(contexto: ContextoMercado, decisao: Decisao, ha_operacao_aberta: bool) -> str:
    """Rótulo curto de 'o que a IA está fazendo agora', para o painel ao vivo."""
    if ha_operacao_aberta:
        return "Operação em andamento…"

    if decisao != Decisao.AGUARDAR:
        return "Confirmando entrada…"

    if contexto.tendencia == "LATERAL":
        return "Mercado lateral…"

    if contexto.reversao_detectada:
        return "Sinal de reversão em análise…"

    ind = contexto.indicadores
    if ind.bb_superior is not None and contexto.candle_atual.fechamento >= ind.bb_superior * 0.995:
        return "Esperando rompimento…"

    if contexto.tendencia in ("ALTA", "BAIXA"):
        return "Esperando pullback…"

    return "Analisando mercado…"
