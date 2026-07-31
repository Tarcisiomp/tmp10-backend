"""
Checklist pré-operação.

Cada item é avaliado de forma independente e objetiva a partir do
contexto de mercado — nada aqui decide sozinho se a operação deve
acontecer (isso é papel do motor de decisão + gestão de risco), mas
serve para o operador humano auditar visualmente o raciocínio da IA
antes de confiar na entrada.
"""

from core.entities import ContextoMercado, ItemChecklist


def _rompimento_valido(contexto: ContextoMercado, direcao: str) -> tuple[bool, str]:
    ind = contexto.indicadores
    preco = contexto.candle_atual.fechamento
    if ind.bb_superior is None or ind.bb_inferior is None:
        return False, "Bandas de Bollinger insuficientes para avaliar rompimento"

    if direcao == "ALTA":
        if preco >= ind.bb_superior:
            return True, f"Fechamento ({preco:.2f}) rompeu a banda superior ({ind.bb_superior:.2f})"
        return False, f"Fechamento ({preco:.2f}) ainda dentro da banda superior ({ind.bb_superior:.2f})"
    else:
        if preco <= ind.bb_inferior:
            return True, f"Fechamento ({preco:.2f}) rompeu a banda inferior ({ind.bb_inferior:.2f})"
        return False, f"Fechamento ({preco:.2f}) ainda dentro da banda inferior ({ind.bb_inferior:.2f})"


def _distancia_vwap_aceitavel(contexto: ContextoMercado, limite_percentual: float = 0.006) -> tuple[bool, str]:
    ind = contexto.indicadores
    preco = contexto.candle_atual.fechamento
    if ind.vwap is None or ind.vwap == 0:
        return False, "VWAP indisponível"

    distancia = abs(preco - ind.vwap) / ind.vwap
    if distancia <= limite_percentual:
        return True, f"Distância da VWAP de {distancia*100:.2f}% (dentro do limite de {limite_percentual*100:.1f}%)"
    return False, f"Distância da VWAP de {distancia*100:.2f}% — acima do limite de {limite_percentual*100:.1f}%"


def gerar_checklist(
    contexto: ContextoMercado, direcao: str, risco_aprovado: bool, motivo_risco: str = ""
) -> list[ItemChecklist]:
    """
    `direcao`: 'ALTA' ou 'BAIXA' — a direção sendo avaliada para a operação.
    `risco_aprovado`/`motivo_risco`: resultado do `GestorDeRisco.pode_operar()`,
    passado de fora porque o checklist não deve conhecer a lógica de risco.
    """
    itens: list[ItemChecklist] = []

    tendencia_ok = contexto.tendencia == direcao
    itens.append(
        ItemChecklist(
            item="Tendência confirmada",
            aprovado=tendencia_ok,
            detalhe=f"Tendência classificada como {contexto.tendencia or 'INDEFINIDA'}",
        )
    )

    volume_ok = (contexto.volume_relativo or 0) >= 1.0
    itens.append(
        ItemChecklist(
            item="Volume acima da média",
            aprovado=volume_ok,
            detalhe=(
                f"Volume {contexto.volume_relativo:.2f}x a média recente"
                if contexto.volume_relativo is not None
                else "Volume médio recente indisponível"
            ),
        )
    )

    rompimento_ok, detalhe_rompimento = _rompimento_valido(contexto, direcao)
    itens.append(ItemChecklist(item="Rompimento válido", aprovado=rompimento_ok, detalhe=detalhe_rompimento))

    ind = contexto.indicadores
    momentum_ok = (
        ind.macd_hist is not None
        and ((ind.macd_hist > 0) if direcao == "ALTA" else (ind.macd_hist < 0))
    )
    itens.append(
        ItemChecklist(
            item="Momentum positivo",
            aprovado=momentum_ok,
            detalhe=f"Histograma do MACD: {ind.macd_hist:.2f}" if ind.macd_hist is not None else "MACD indisponível",
        )
    )

    volatilidade_ok = contexto.classe_volatilidade == "NORMAL"
    itens.append(
        ItemChecklist(
            item="Volatilidade adequada",
            aprovado=volatilidade_ok,
            detalhe=f"Volatilidade classificada como {contexto.classe_volatilidade or 'INDEFINIDA'}",
        )
    )

    vwap_ok, detalhe_vwap = _distancia_vwap_aceitavel(contexto)
    itens.append(ItemChecklist(item="Distância da VWAP aceitável", aprovado=vwap_ok, detalhe=detalhe_vwap))

    itens.append(
        ItemChecklist(
            item="Gestão de risco aprovada",
            aprovado=risco_aprovado,
            detalhe=motivo_risco or "Dentro de todos os limites de risco configurados",
        )
    )

    return itens
