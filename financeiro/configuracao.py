"""
Configuração Financeira geral — só o que NÃO é custo por operação (isso
agora vive em custos_operacionais, por ativo + corretora — ver
custos/calculo.py e database.repository.obter_custo_vigente).
"""

CHAVE_CONFIG_FINANCEIRA = "config_financeira"

CONFIG_FINANCEIRA_PADRAO: dict = {
    "percentual_imposto": 20.0,          # % sobre o lucro líquido do período (Day Trade)
    "patrimonio_inicial": 0.0,           # usado no painel de evolução de patrimônio
}
