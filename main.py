"""
Ponto de entrada da aplicação FastAPI.

Roda com: uvicorn main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from dashboard.routes import router as dashboard_router
from dashboard.routes import router_custos, router_financeiro
from logs.logger import logger

app = FastAPI(
    title=settings.app_name,
    description=(
        "Agente de Inteligência Artificial para análise e decisão de operações "
        "no Mini Índice (WIN). Etapa 1: arquitetura completa, sem integração com "
        "corretora e sem envio de ordens reais."
    ),
    version="0.1.0",
)

# Libera o frontend (trader.tmp10.com.br) a chamar esta API.
# Ajuste a lista conforme os domínios reais em produção.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://trader.tmp10.com.br",
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_router)
app.include_router(router_financeiro)
app.include_router(router_custos)


@app.on_event("startup")
async def startup_event() -> None:
    logger.info(f"{settings.app_name} iniciado em modo '{settings.app_env}'.")
    logger.info("Modo de operação: PAPER TRADING (nenhuma ordem real será enviada nesta etapa).")


@app.get("/", tags=["root"])
def raiz() -> dict:
    return {
        "app": settings.app_name,
        "status": "online",
        "modo": "PAPER_TRADING",
        "docs": "/docs",
    }


@app.get("/health", tags=["root"])
def health_check() -> dict:
    return {"status": "ok"}
