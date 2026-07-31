"""
Configurações centrais da aplicação.

Carrega variáveis de ambiente (.env) usando pydantic-settings.
Nenhum outro módulo deve ler variáveis de ambiente diretamente:
tudo passa por aqui, para manter uma única fonte de verdade.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Aplicação
    app_name: str = "TraderIA WIN"
    app_env: str = "development"
    log_level: str = "INFO"

    # Banco de dados
    database_url: str = "postgresql+psycopg2://traderia:traderia@localhost:5432/traderia_win"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Ativo
    ativo_padrao: str = "WINFUT"

    # Gestão de risco (defaults conservadores; sobrescrever via .env)
    risk_stop_por_operacao: float = 100
    risk_stop_diario: float = 500
    risk_meta_diaria: float = 800
    risk_max_drawdown: float = 1000
    risk_max_operacoes_dia: int = 10
    risk_limite_financeiro_diario: float = 2000

    # Integração futura com corretora (deixado em branco propositalmente)
    profit_pro_host: str | None = None
    profit_pro_port: int | None = None
    profit_pro_token: str | None = None


settings = Settings()
