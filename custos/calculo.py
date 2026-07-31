"""
Cálculo da Taxa Total por Contrato — SEMPRE a partir dos campos
cadastrados em custos_operacionais, nunca de um valor fixo no código.
"""


def calcular_taxa_total(
    corretagem: float,
    emolumentos: float,
    registro: float,
    liquidacao: float,
    iss: float,
    outras_taxas: list[dict] | None = None,
) -> float:
    total = corretagem + emolumentos + registro + liquidacao + iss
    for taxa in (outras_taxas or []):
        total += taxa.get("valor", 0.0)
    return round(total, 4)
