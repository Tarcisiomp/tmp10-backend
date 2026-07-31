"""
Valor por ponto de cada instrumento — a peça que faltava para transformar
"pontos" em "reais" de verdade nos resultados.

Cada contrato futuro na B3 tem um valor fixo por ponto de variação. Isso
é definido pela B3, não pela corretora, e não muda com frequência. Manter
isso centralizado aqui evita number mágicos espalhados pelo código.
"""

# Valor de cada ponto de variação, em R$, por contrato (não por lote).
# Fonte: especificações de contrato da B3. Ajuste aqui se a B3 alterar
# o valor de algum contrato — é o único lugar que precisa mudar.
VALOR_POR_PONTO: dict[str, float] = {
    "WIN": 0.20,   # Mini Índice Bovespa
    "IND": 1.00,   # Índice Bovespa (contrato cheio)
    "WDO": 10.00,  # Mini Dólar
    "DOL": 10.00,  # Dólar (contrato cheio)
}

VALOR_POR_PONTO_PADRAO = 1.00  # usado se o ativo não for reconhecido — mantém pontos == reais, como antes

# NOTA: o custo de bolsa/corretagem NÃO fica mais aqui. Isso é uma TAXA
# (varia por corretora, muda com o tempo), diferente do valor por ponto
# acima (que é uma especificação de contrato definida pela B3, igual
# pra todo mundo). Custos agora vêm SEMPRE de custos_operacionais no
# banco de dados — ver custos/calculo.py e
# database.repository.obter_custo_vigente. Isso evita ter que mexer no
# código toda vez que uma corretora muda uma taxa.


def obter_valor_por_ponto(ativo: str) -> float:
    """
    Resolve o valor por ponto a partir do código do ativo/contrato.
    Contratos futuros na B3 vêm com sufixo de vencimento (ex.: 'WINQ26',
    'WDOZ26'), então comparamos pelo prefixo, não pelo nome exato.
    """
    ativo_upper = (ativo or "").upper()
    for prefixo, valor in VALOR_POR_PONTO.items():
        if ativo_upper.startswith(prefixo):
            return valor
    return VALOR_POR_PONTO_PADRAO
