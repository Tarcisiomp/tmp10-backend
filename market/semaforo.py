"""
Semáforo do mercado.

Resume, em 🟢/🟡/🔴, cinco dimensões do momento atual de mercado:
tendência, fluxo, volatilidade, liquidez e horário. Isso não decide nada
sozinho — é uma leitura rápida para o operador humano, complementar ao
Score da IA e ao checklist da operação.
"""

from dataclasses import dataclass

from core.entities import ContextoMercado
from market.pregao import StatusPregao


@dataclass
class ItemSemaforo:
    dimensao: str
    status: str  # "FAVORAVEL" | "ATENCAO" | "DESFAVORAVEL"
    detalhe: str


def _semaforo_tendencia(contexto: ContextoMercado) -> ItemSemaforo:
    if contexto.tendencia in ("ALTA", "BAIXA"):
        return ItemSemaforo("Tendência", "FAVORAVEL", f"Tendência de {contexto.tendencia.lower()} definida")
    if contexto.tendencia == "LATERAL":
        return ItemSemaforo("Tendência", "ATENCAO", "Mercado sem direção definida (lateral)")
    return ItemSemaforo("Tendência", "ATENCAO", "Tendência ainda não classificada")


def _semaforo_fluxo(contexto: ContextoMercado) -> ItemSemaforo:
    obv = contexto.indicadores.obv
    if obv is None:
        return ItemSemaforo("Fluxo", "ATENCAO", "OBV indisponível")
    if abs(obv) < 1:
        return ItemSemaforo("Fluxo", "ATENCAO", "Fluxo comprador/vendedor equilibrado")
    lado = "comprador" if obv > 0 else "vendedor"
    return ItemSemaforo("Fluxo", "FAVORAVEL", f"Fluxo {lado} dominante (OBV {obv:.0f})")


def _semaforo_volatilidade(contexto: ContextoMercado) -> ItemSemaforo:
    mapa = {
        "NORMAL": ("FAVORAVEL", "Volatilidade dentro do padrão"),
        "BAIXA": ("ATENCAO", "Volatilidade baixa: movimentos podem ser insuficientes"),
        "ALTA": ("DESFAVORAVEL", "Volatilidade alta: risco de movimentos bruscos"),
    }
    status, detalhe = mapa.get(contexto.classe_volatilidade or "", ("ATENCAO", "Volatilidade ainda não classificada"))
    return ItemSemaforo("Volatilidade", status, detalhe)


def _semaforo_liquidez(contexto: ContextoMercado) -> ItemSemaforo:
    if contexto.volume_relativo is None:
        return ItemSemaforo("Liquidez", "ATENCAO", "Volume médio recente indisponível")
    if contexto.volume_relativo >= 0.8:
        return ItemSemaforo("Liquidez", "FAVORAVEL", f"Volume em {contexto.volume_relativo:.1f}x a média recente")
    return ItemSemaforo("Liquidez", "DESFAVORAVEL", f"Volume {contexto.volume_relativo:.1f}x abaixo da média recente")


def _semaforo_horario(status_pregao: StatusPregao) -> ItemSemaforo:
    if not status_pregao.aberto:
        return ItemSemaforo("Horário", "DESFAVORAVEL", status_pregao.motivo)
    if not status_pregao.aceita_novas_operacoes:
        return ItemSemaforo("Horário", "ATENCAO", status_pregao.motivo)
    return ItemSemaforo("Horário", "FAVORAVEL", status_pregao.motivo)


def calcular_semaforo(contexto: ContextoMercado, status_pregao: StatusPregao) -> list[ItemSemaforo]:
    return [
        _semaforo_tendencia(contexto),
        _semaforo_fluxo(contexto),
        _semaforo_volatilidade(contexto),
        _semaforo_liquidez(contexto),
        _semaforo_horario(status_pregao),
    ]
