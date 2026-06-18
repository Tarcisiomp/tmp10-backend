// Corrigir frete de TODOS os pedidos errados automaticamente
app.post('/api/fix-all-frete', async (req, res) => {
  res.json({ ok: true, message: 'Corrigindo frete de todos os pedidos em background...' })
  ;(async () => {
    const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
    if (!accounts?.length) return
    const token = await getToken(accounts[0])
    let offset = 0, fixed = 0, errors = 0

    while (true) {
      const { data: orders } = await sb.from('ml_orders')
        .select('id, ml_order_id, shipment_id, total_amount, sale_fee')
        .not('shipment_id', 'is', null)
        .not('status', 'in', '(cancelado)')
        .or('paid_amount.gte.total_amount,paid_amount.eq.0,paid_amount.is.null')
        .range(offset, offset + 29)

      if (!orders?.length) break

      for (const order of orders) {
        try {
          const { freteVendedor } = await calcShippingCost(order.shipment_id, token)
          const paidAmount = (order.total_amount||0) - (order.sale_fee||0) - freteVendedor
          await sb.from('ml_orders').update({
            shipping_cost_ml: freteVendedor,
            paid_amount: paidAmount,
            updated_at: new Date().toISOString()
          }).eq('id', order.id)
          fixed++
          console.log(✅ ${order.ml_order_id}: frete=${freteVendedor})
          await new Promise(r => setTimeout(r, 500))
        } catch(e) { errors++; console.log(❌ ${order.ml_order_id}: ${e.message}) }
      }
      offset += 30
      await new Promise(r => setTimeout(r, 3000))
    }
    console.log(🎉 Fix-all-frete: ${fixed} corrigidos, ${errors} erros)
  })()
})
