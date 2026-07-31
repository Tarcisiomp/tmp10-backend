"""
Horário de pregão do Mini Índice (WIN).

Centraliza a regra de horário em um único lugar. Nenhum outro módulo
deve "saber" o horário de pregão por conta própria — todos consultam
estas funções, para que mudar o horário (ex.: horário de verão, ajuste
da B3) seja uma alteração em um único arquivo. Os horários e dias podem
ser sobrescritos (ver painel de configurações), mas os padrões abaixo
refletem o pregão real do Mini Índice.
"""

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

FUSO_HORARIO_B3 = ZoneInfo("America/Sao_Paulo")

HORARIO_ABERTURA_PADRAO = time(9, 0)
HORARIO_FECHAMENTO_PADRAO = time(17, 45)

# A partir deste horário, o sistema para de abrir NOVAS operações,
# mesmo que o pregão ainda esteja tecnicamente aberto — evita ficar
# posicionado perto do encerramento.
HORARIO_LIMITE_NOVAS_OPERACOES_PADRAO = time(17, 30)

# A partir deste horário, qualquer operação ainda aberta é encerrada
# automaticamente (fechamento forçado de segurança).
HORARIO_FECHAMENTO_FORCADO_PADRAO = time(17, 40)

DIAS_PERMITIDOS_PADRAO = (0, 1, 2, 3, 4)  # 0=segunda ... 6=domingo


@dataclass
class StatusPregao:
    aberto: bool
    aceita_novas_operacoes: bool
    deve_fechar_posicoes_abertas: bool
    horario_atual: time
    horario_fechamento: time
    motivo: str


def _agora_brasilia(agora: datetime | None = None) -> datetime:
    if agora is None:
        agora = datetime.now(tz=FUSO_HORARIO_B3)
    elif agora.tzinfo is None:
        agora = agora.replace(tzinfo=FUSO_HORARIO_B3)
    else:
        agora = agora.astimezone(FUSO_HORARIO_B3)
    return agora


def obter_status_pregao(
    agora: datetime | None = None,
    horario_abertura: time = HORARIO_ABERTURA_PADRAO,
    horario_fechamento: time = HORARIO_FECHAMENTO_PADRAO,
    horario_limite_novas_operacoes: time = HORARIO_LIMITE_NOVAS_OPERACOES_PADRAO,
    horario_fechamento_forcado: time = HORARIO_FECHAMENTO_FORCADO_PADRAO,
    dias_permitidos: tuple[int, ...] = DIAS_PERMITIDOS_PADRAO,
) -> StatusPregao:
    """
    Calcula o status do pregão para o instante `agora` (ou o momento atual,
    se não informado). Os parâmetros de horário/dias têm os valores reais
    do Mini Índice como padrão, mas podem ser sobrescritos pelo painel de
    configurações (ver `database.repository.obter_configuracoes`).
    """
    agora_local = _agora_brasilia(agora)
    hora_atual = agora_local.time()
    dia_permitido = agora_local.weekday() in dias_permitidos

    if not dia_permitido:
        return StatusPregao(
            aberto=False, aceita_novas_operacoes=False, deve_fechar_posicoes_abertas=True,
            horario_atual=hora_atual, horario_fechamento=horario_fechamento,
            motivo="Fora de dia permitido para operar",
        )

    if hora_atual < horario_abertura or hora_atual >= horario_fechamento:
        return StatusPregao(
            aberto=False, aceita_novas_operacoes=False, deve_fechar_posicoes_abertas=True,
            horario_atual=hora_atual, horario_fechamento=horario_fechamento,
            motivo=f"Fora do horário de pregão ({horario_abertura}–{horario_fechamento})",
        )

    if hora_atual >= horario_fechamento_forcado:
        return StatusPregao(
            aberto=True, aceita_novas_operacoes=False, deve_fechar_posicoes_abertas=True,
            horario_atual=hora_atual, horario_fechamento=horario_fechamento,
            motivo="Perto do fechamento: encerrando posições abertas por segurança",
        )

    if hora_atual >= horario_limite_novas_operacoes:
        return StatusPregao(
            aberto=True, aceita_novas_operacoes=False, deve_fechar_posicoes_abertas=False,
            horario_atual=hora_atual, horario_fechamento=horario_fechamento,
            motivo="Perto do fechamento: sem novas operações, mantendo posição atual",
        )

    return StatusPregao(
        aberto=True, aceita_novas_operacoes=True, deve_fechar_posicoes_abertas=False,
        horario_atual=hora_atual, horario_fechamento=horario_fechamento,
        motivo="Dentro do horário de pregão",
    )
