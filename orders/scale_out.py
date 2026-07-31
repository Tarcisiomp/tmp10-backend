"""
Configuração de saída em partes (scale-out) — a estratégia validada com
dado real de 5,5 meses (ver docs/ESTUDO_HORARIOS.md e o histórico de
testes com WIN/WDO): entra com N contratos, cada um sai num alvo fixo
(em pontos, não em múltiplos de ATR), e o último contrato "corre" com
um stop que vai subindo (trailing) conforme o preço avança.

Esses valores são os mesmos usados nos arquivos NTSL
(ntsl/traderia_win_completo.ntsl e ntsl/traderia_wdo_completo.ntsl) —
qualquer ajuste deveria ser feito nos dois lugares, ou futuramente
extraído para uma fonte única de configuração compartilhada.
"""

from dataclasses import dataclass

from core.entities import Lado


@dataclass(frozen=True)
class ConfiguracaoScaleOut:
    quantidade_contratos: int
    alvos_pontos: tuple[float, ...]  # um alvo por contrato "fatiado"; o último contrato não tem alvo (corre)
    stop_inicial_pontos: float
    inicio_trailing_pontos: float
    passo_trailing_pontos: float = 100.0


# Configuração validada por ativo — ver histórico de testes no chat e
# docs/ESTUDO_HORARIOS.md para o racional por trás de cada número.
CONFIGURACOES_SCALE_OUT: dict[str, ConfiguracaoScaleOut] = {
    "WIN": ConfiguracaoScaleOut(
        quantidade_contratos=4,
        alvos_pontos=(150, 200, 350),
        stop_inicial_pontos=150,
        inicio_trailing_pontos=250,
    ),
    "WDO": ConfiguracaoScaleOut(
        quantidade_contratos=4,
        alvos_pontos=(150, 200, 350),
        stop_inicial_pontos=30,
        inicio_trailing_pontos=250,
    ),
}


def obter_configuracao_scale_out(ativo: str) -> ConfiguracaoScaleOut | None:
    ativo_upper = (ativo or "").upper()
    for prefixo, config in CONFIGURACOES_SCALE_OUT.items():
        if ativo_upper.startswith(prefixo):
            return config
    return None


def config_scale_out_de_dict(d: dict) -> ConfiguracaoScaleOut:
    """Constrói uma ConfiguracaoScaleOut a partir de um dict (vindo do painel de configurações)."""
    return ConfiguracaoScaleOut(
        quantidade_contratos=int(d["quantidade_contratos"]),
        alvos_pontos=tuple(float(x) for x in d["alvos_pontos"]),
        stop_inicial_pontos=float(d["stop_inicial_pontos"]),
        inicio_trailing_pontos=float(d["inicio_trailing_pontos"]),
        passo_trailing_pontos=float(d.get("passo_trailing_pontos", 100.0)),
    )


def config_scale_out_para_dict(config: ConfiguracaoScaleOut) -> dict:
    return {
        "quantidade_contratos": config.quantidade_contratos,
        "alvos_pontos": list(config.alvos_pontos),
        "stop_inicial_pontos": config.stop_inicial_pontos,
        "inicio_trailing_pontos": config.inicio_trailing_pontos,
        "passo_trailing_pontos": config.passo_trailing_pontos,
    }


def calcular_stop_atual_pontos(pontos_ganho: float, config: ConfiguracaoScaleOut) -> float:
    """
    Retorna a distância do stop em relação ao preço de entrada, EM
    PONTOS COM SINAL (positivo = travando lucro, negativo = ainda no
    prejuízo inicial). Ex.: retorno de -150 significa "stop 150 pontos
    ABAIXO da entrada" (na compra).
    """
    ultimo_alvo = config.alvos_pontos[-1] if config.alvos_pontos else 0

    if pontos_ganho >= config.inicio_trailing_pontos:
        nivel = config.inicio_trailing_pontos + (
            (pontos_ganho - config.inicio_trailing_pontos) // config.passo_trailing_pontos
        ) * config.passo_trailing_pontos
        return nivel - config.passo_trailing_pontos
    if pontos_ganho >= ultimo_alvo:
        return 0.0  # zero a zero
    return -config.stop_inicial_pontos


def preco_do_stop(preco_entrada: float, lado: Lado, stop_pontos: float) -> float:
    sinal = 1 if lado == Lado.COMPRA else -1
    return preco_entrada + sinal * stop_pontos


def preco_do_alvo(preco_entrada: float, lado: Lado, alvo_pontos: float) -> float:
    sinal = 1 if lado == Lado.COMPRA else -1
    return preco_entrada + sinal * alvo_pontos
