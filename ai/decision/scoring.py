"""
Scoring por fatores — a base do "Score da IA" e da barra de confiança.

Cada fator retorna um valor de 0 a 100 que representa o quão FAVORÁVEL
aquele aspecto do mercado está para a direção (COMPRA/VENDA) sendo
avaliada. 50 é neutro. Isso é o que alimenta:

- O Score da IA geral (média ponderada dos 6 fatores)
- A barra "Confiança da decisão" com o detalhamento por fator
- O checklist pré-operação

Assim como o motor de decisão, esta é uma implementação de referência
heurística — clara, comentada e substituível por um modelo treinado no
futuro (ver `MotorDeDecisaoML` em `ai/decision/engine.py`).
"""

from core.entities import ContextoMercado, IndicadoresSnapshot

PESOS_FATORES = {
    "tendencia": 0.25,
    "momentum": 0.20,
    "fluxo": 0.15,
    "volume": 0.15,
    "volatilidade": 0.15,
    "contexto": 0.10,
}


def _clamp(valor: float, minimo: float = 0.0, maximo: float = 100.0) -> float:
    return max(minimo, min(maximo, valor))


def score_tendencia(contexto: ContextoMercado, direcao: str) -> float:
    """direcao: 'ALTA' ou 'BAIXA' — a direção que está sendo avaliada."""
    if contexto.tendencia is None or contexto.tendencia == "INDEFINIDO":
        return 50.0
    if contexto.tendencia == "LATERAL":
        return 35.0
    return 85.0 if contexto.tendencia == direcao else 15.0


def score_momentum(indicadores: IndicadoresSnapshot, direcao: str) -> float:
    pontos = []

    if indicadores.rsi is not None:
        if direcao == "ALTA":
            # RSI baixo (sobrevendido) favorece continuação de compra pós-repique
            pontos.append(_clamp(100 - indicadores.rsi))
        else:
            pontos.append(_clamp(indicadores.rsi))

    if indicadores.macd_hist is not None:
        favor = indicadores.macd_hist > 0 if direcao == "ALTA" else indicadores.macd_hist < 0
        intensidade = min(abs(indicadores.macd_hist) * 20, 40)  # satura a contribuição
        pontos.append(65 + intensidade if favor else 35 - intensidade)

    if not pontos:
        return 50.0
    return _clamp(sum(pontos) / len(pontos))


def score_fluxo(indicadores: IndicadoresSnapshot, direcao: str) -> float:
    """
    Usa o OBV como proxy de fluxo comprador/vendedor. OBV positivo e
    crescente sugere fluxo comprador dominante.
    """
    if indicadores.obv is None:
        return 50.0
    favor = indicadores.obv > 0 if direcao == "ALTA" else indicadores.obv < 0
    return 70.0 if favor else 30.0


def score_volume(contexto: ContextoMercado) -> float:
    """Volume relativo à média recente — não depende da direção, é sobre relevância."""
    if contexto.volume_relativo is None:
        return 50.0
    # volume 50% acima da média = ótimo (100); volume igual à média = neutro (55);
    # volume muito abaixo da média = fraco (20)
    if contexto.volume_relativo >= 1.5:
        return 95.0
    if contexto.volume_relativo >= 1.0:
        return 55.0 + (contexto.volume_relativo - 1.0) * 80
    return _clamp(55.0 * contexto.volume_relativo)


def score_volatilidade(contexto: ContextoMercado) -> float:
    """Volatilidade NORMAL é o cenário ideal; ALTA e BAIXA demais atrapalham."""
    mapa = {"NORMAL": 85.0, "ALTA": 40.0, "BAIXA": 45.0, "INDEFINIDO": 50.0}
    return mapa.get(contexto.classe_volatilidade or "INDEFINIDO", 50.0)


def score_contexto(contexto: ContextoMercado, direcao: str) -> float:
    """
    Combina padrões gráficos detectados e o momento do pregão (evita dar
    contexto favorável perto do fechamento, quando o sistema já está
    prestes a parar de operar de qualquer forma).

    Cada padrão só soma pontos a favor da DIREÇÃO que ele confirma —
    um engolfo de alta não deve turbinar um Score de venda, por exemplo.
    """
    pontuacao = 50.0
    padroes = contexto.padroes_detectados

    if (direcao == "ALTA" and "ENGOLFO_ALTA" in padroes) or (direcao == "BAIXA" and "ENGOLFO_BAIXA" in padroes):
        pontuacao += 20
    if "MARTELO" in padroes and direcao == "ALTA":
        pontuacao += 10
    if "DOJI" in padroes:
        pontuacao -= 10
    if (direcao == "ALTA" and "ROMPIMENTO_ALTA" in padroes) or (direcao == "BAIXA" and "ROMPIMENTO_BAIXA" in padroes):
        pontuacao += 25

    return _clamp(pontuacao)


def calcular_fatores(contexto: ContextoMercado, direcao: str) -> dict[str, float]:
    """Retorna o dict {fator: score 0-100} para a direção avaliada."""
    return {
        "tendencia": round(score_tendencia(contexto, direcao), 1),
        "momentum": round(score_momentum(contexto.indicadores, direcao), 1),
        "fluxo": round(score_fluxo(contexto.indicadores, direcao), 1),
        "volume": round(score_volume(contexto), 1),
        "volatilidade": round(score_volatilidade(contexto), 1),
        "contexto": round(score_contexto(contexto, direcao), 1),
    }


def calcular_score_ia(fatores: dict[str, float]) -> float:
    """Combina os fatores em um único Score da IA (0-100), ponderado."""
    total = sum(fatores.get(nome, 50.0) * peso for nome, peso in PESOS_FATORES.items())
    return round(total, 1)
