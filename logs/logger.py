"""
Configuração central de logging estruturado (usando loguru).

Todo módulo do sistema deve importar `logger` daqui, nunca usar
`print()` ou configurar seu próprio logging — isso garante que TUDO
fica registrado de forma consistente, conforme pedido no escopo
("Registrar absolutamente tudo").
"""

import sys
from pathlib import Path

from loguru import logger

from config.settings import settings

_LOG_DIR = Path(__file__).parent / "arquivos"
_LOG_DIR.mkdir(exist_ok=True)

logger.remove()  # remove o handler padrão

logger.add(
    sys.stdout,
    level=settings.log_level,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | <cyan>{module}</cyan> - {message}",
)

logger.add(
    _LOG_DIR / "traderia_{time:YYYY-MM-DD}.log",
    level=settings.log_level,
    rotation="00:00",
    retention="90 days",
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module} - {message}",
)


def log_decisao(ativo: str, decisao: str, confianca: float, motivos: list[str]) -> None:
    """Helper para registrar decisões do motor de forma padronizada."""
    logger.info(
        f"[DECISAO] ativo={ativo} decisao={decisao} confianca={confianca:.2f} motivos={motivos}"
    )


def log_ordem(evento: str, ativo: str, lado: str, preco: float, motivo: str) -> None:
    """Helper para registrar abertura/fechamento de ordens simuladas."""
    logger.info(f"[ORDEM:{evento}] ativo={ativo} lado={lado} preco={preco} motivo={motivo}")


def log_risco(motivo_bloqueio: str) -> None:
    logger.warning(f"[RISCO] Operações bloqueadas: {motivo_bloqueio}")
