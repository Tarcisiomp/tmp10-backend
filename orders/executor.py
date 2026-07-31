"""
Executor de ordens.

Nesta etapa, existe APENAS execução simulada (paper trading). Nenhuma
ordem real é enviada a nenhuma corretora — isso é proposital, conforme
pedido explicitamente no escopo do projeto.

A integração real (envio de ordens de verdade) deve ser implementada
futuramente como uma nova classe que implementa `ExecutorDeOrdens`,
mantendo o mesmo contrato usado por simulation/ e backtest/.
"""

from datetime import datetime
from uuid import uuid4

from core.entities import Decisao, DecisaoTrade, Lado, OrdemSimulada
from core.interfaces import ExecutorDeOrdens
from market.instrumentos import obter_valor_por_ponto
from orders.niveis import calcular_niveis_operacao
from orders.scale_out import ConfiguracaoScaleOut


class ExecutorSimulado(ExecutorDeOrdens):
    """
    Executa ordens apenas em memória/banco, sem tocar em corretora real.

    Todo resultado é calculado em camadas explícitas, sempre visíveis e
    nunca misturadas:
    - `resultado_pontos`: a variação de preço pura (sem dinheiro nenhum)
    - `resultado_financeiro_bruto`: em R$, antes de qualquer custo
    - `custo_b3`: custo operacional da operação completa (compra + venda)
    - `resultado_financeiro`: em R$, JÁ LÍQUIDO do custo operacional

    O custo por contrato de cada ativo é passado de fora (`custos_por_ativo`)
    — vem sempre de custos_operacionais no banco (ver
    database.repository.obter_custo_vigente), NUNCA um valor fixo aqui.
    Se um ativo não tiver custo informado, o custo é 0 (evita inventar
    número — melhor mostrar 0 e chamar atenção do que subestimar lucro
    por engano com um valor genérico).

    Não inclui Imposto de Renda — o IR sobre day trade é apurado
    MENSALMENTE sobre o resultado líquido do mês (20% sobre o lucro,
    compensando perdas do próprio mês), não faz sentido descontar por
    operação individual. Isso é calculado à parte, no nível de relatório
    (ver `backtest/engine.py` e `financeiro/calculo.py`).
    """

    def __init__(self, custos_por_ativo: dict[str, float] | None = None):
        self._custos_por_ativo = custos_por_ativo or {}

    def _custo_por_contrato(self, ativo: str) -> float:
        ativo_upper = (ativo or "").upper()
        for prefixo, valor in self._custos_por_ativo.items():
            if ativo_upper.startswith(prefixo.upper()):
                return valor
        return 0.0

    def abrir_ordem(self, decisao: DecisaoTrade, quantidade: int) -> OrdemSimulada:
        if decisao.decisao == Decisao.AGUARDAR:
            raise ValueError("Não é possível abrir ordem para uma decisão de AGUARDAR")

        lado = Lado.COMPRA if decisao.decisao == Decisao.COMPRAR else Lado.VENDA
        preco_entrada = decisao.contexto.candle_atual.fechamento
        niveis = calcular_niveis_operacao(preco_entrada, lado, decisao.contexto.indicadores.atr)

        return OrdemSimulada(
            ativo=decisao.contexto.ativo,
            lado=lado,
            preco_entrada=preco_entrada,
            quantidade=quantidade,
            timestamp_entrada=decisao.timestamp,
            motivo_entrada="; ".join(decisao.motivos),
            aberta=True,
            niveis=niveis,
            score_ia_entrada=decisao.score_ia,
            confianca_entrada=decisao.confianca,
        )

    def abrir_ordens_scale_out(
        self, decisao: DecisaoTrade, config: ConfiguracaoScaleOut
    ) -> list[OrdemSimulada]:
        """
        Abre N ordens de 1 contrato cada (uma "fatia" por alvo, mais um
        "contrato corredor" sem alvo fixo), todas com o mesmo preço de
        entrada e ligadas pelo mesmo `grupo_entrada_id`.
        """
        if decisao.decisao == Decisao.AGUARDAR:
            raise ValueError("Não é possível abrir ordem para uma decisão de AGUARDAR")

        lado = Lado.COMPRA if decisao.decisao == Decisao.COMPRAR else Lado.VENDA
        preco_entrada = decisao.contexto.candle_atual.fechamento
        niveis = calcular_niveis_operacao(preco_entrada, lado, decisao.contexto.indicadores.atr)
        grupo_id = str(uuid4())
        motivo = "; ".join(decisao.motivos)

        # um alvo por contrato "fatiado"; contratos extras (sem alvo
        # correspondente) viram "corredores" — só saem por stop/trailing
        alvos: list[float | None] = list(config.alvos_pontos)
        while len(alvos) < config.quantidade_contratos:
            alvos.append(None)

        ordens = []
        for alvo_pontos in alvos[: config.quantidade_contratos]:
            ordens.append(
                OrdemSimulada(
                    ativo=decisao.contexto.ativo,
                    lado=lado,
                    preco_entrada=preco_entrada,
                    quantidade=1,
                    timestamp_entrada=decisao.timestamp,
                    motivo_entrada=motivo,
                    aberta=True,
                    niveis=niveis,
                    score_ia_entrada=decisao.score_ia,
                    confianca_entrada=decisao.confianca,
                    grupo_entrada_id=grupo_id,
                    alvo_pontos=alvo_pontos,
                )
            )
        return ordens

    def fechar_ordem(
        self, ordem: OrdemSimulada, preco_saida: float, motivo_saida: str, timestamp_saida=None
    ) -> OrdemSimulada:
        multiplicador = 1 if ordem.lado == Lado.COMPRA else -1
        pontos = (preco_saida - ordem.preco_entrada) * multiplicador
        valor_por_ponto = obter_valor_por_ponto(ordem.ativo)
        financeiro_bruto = pontos * valor_por_ponto * ordem.quantidade
        custo_b3 = self._custo_por_contrato(ordem.ativo) * ordem.quantidade
        financeiro_liquido = financeiro_bruto - custo_b3

        return OrdemSimulada(
            ativo=ordem.ativo,
            lado=ordem.lado,
            preco_entrada=ordem.preco_entrada,
            quantidade=ordem.quantidade,
            timestamp_entrada=ordem.timestamp_entrada,
            motivo_entrada=ordem.motivo_entrada,
            preco_saida=preco_saida,
            timestamp_saida=timestamp_saida or datetime.utcnow(),
            motivo_saida=motivo_saida,
            resultado_pontos=round(pontos, 2),
            resultado_financeiro_bruto=round(financeiro_bruto, 2),
            custo_b3=round(custo_b3, 2),
            resultado_financeiro=round(financeiro_liquido, 2),
            aberta=False,
            niveis=ordem.niveis,
            score_ia_entrada=ordem.score_ia_entrada,
            confianca_entrada=ordem.confianca_entrada,
            grupo_entrada_id=ordem.grupo_entrada_id,
            alvo_pontos=ordem.alvo_pontos,
        )


class ExecutorRealCorretora(ExecutorDeOrdens):
    """
    NÃO IMPLEMENTADO NESTA ETAPA.

    Nenhuma ordem real deve ser enviada a nenhuma corretora enquanto esta
    classe não for implementada intencionalmente em uma etapa futura,
    após validação extensiva em paper trading e backtest.
    """

    def abrir_ordem(self, decisao: DecisaoTrade, quantidade: int) -> OrdemSimulada:
        raise NotImplementedError(
            "Envio de ordens reais não está habilitado nesta etapa do projeto."
        )

    def abrir_ordens_scale_out(self, decisao: DecisaoTrade, config) -> list[OrdemSimulada]:
        raise NotImplementedError(
            "Envio de ordens reais não está habilitado nesta etapa do projeto."
        )

    def fechar_ordem(
        self, ordem: OrdemSimulada, preco_saida: float, motivo_saida: str, timestamp_saida=None
    ) -> OrdemSimulada:
        raise NotImplementedError(
            "Envio de ordens reais não está habilitado nesta etapa do projeto."
        )
