"""
Cria todas as tabelas no banco de dados a partir dos models.

Uso: python -m database.init_db

Para produção, o ideal é migrar isso para Alembic (já incluído nas
dependências) e gerar migrations versionadas. Este script é o ponto
de partida rápido de desenvolvimento.
"""

from database import models  # noqa: F401  (garante que os models sejam registrados)
from database.connection import Base, engine


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    print("Tabelas criadas/atualizadas com sucesso.")


if __name__ == "__main__":
    init_db()
