require('dotenv').config()
const express = require('express')
const cors = require('cors')
const axios = require('axios')
const cron = require('node-cron')
const { createClient } = require('@supabase/supabase-js')

const app = express()
app.use(cors())
app.use(express.json())

const sb = createClient(
  process.env.SUPABASE_URL || 'https://foshqdjgbcigggrcjtap.supabase.co',
  process.env.SUPABASE_SERVICE_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZvc2hxZGpnYmNpZ2dncmNqdGFwIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3OTQwMDAyMSwiZXhwIjoyMDk0OTc2MDIxfQ.6h_Pouyxs73jug7JJtCtfj50JJPi1whWnAkdJuPNSoI'
)

const ML_CLIENT_ID     = process.env.ML_CLIENT_ID     || '4022957335913783'
const ML_CLIENT_SECRET = process.env.ML_CLIENT_SECRET || 'f9jB9yc6UvrAnz4kjT6u02xMxjbvn7z3'
const RAILWAY_URL      = 'https://web-production-82c10.up.railway.app'

// ── Auth ──────────────────────────────────────────────────────────
app.get('/ml/auth/:accountId', (req, res) => {
  const redirectUri = `${RAILWAY_URL}/ml/callback`
  const url = `https://auth.mercadolivre.com.br/authorization?response_type=code&client_id=${ML_CLIENT_ID}&redirect_uri=${encodeURIComponent(redirectUri)}&state=${req.params.accountId}`
  res.redirect(url)
})

app.get('/ml/callback', async (req, res) => {
  const { code, state: accountId } = req.query
  try {
    const { data: tok } = await axios.post('https://api.mercadolibre.com/oauth/token', {
      grant_type: 'authorization_code',
      client_id: ML_CLIENT_ID,
      client_secret: ML_CLIENT_SECRET,
      code,
      redirect_uri: `${RAILWAY_URL}/ml/callback`
    })
    const { data: userInfo } = await axios.get(
      `https://api.mercadolibre.com/users/${tok.user_id}`,
      { headers: { Authorization: `Bearer ${tok.access_token}` } }
    )
    await sb.from('ml_accounts').upsert({
      account_id: accountId,
      ml_user_id: String(tok.user_id),
      nickname: userInfo.nickname,
      access_token: tok.access_token,
      refresh_token: tok.refresh_token,
      expires_at: new Date(Date.now() + tok.expires_in * 1000).toISOString(),
      active: true
    }, { onConflict: 'ml_user_id' })
    await syncMLOrders({ ml_user_id: String(tok.user_id), access_token: tok.access_token, nickname: userInfo.nickname })
    res.redirect(`https://tmp10.com.br?ml_connected=true&nickname=${userInfo.nickname}`)
  } catch (e) {
    console.error('Auth error:', e.response?.data || e.message)
    res.redirect(`https://tmp10.com.br?ml_error=true`)
  }
})

// ── Token ─────────────────────────────────────────────────────────
async function refreshToken(account) {
  try {
    const { data } = await axios.post('https://api.mercadolibre.com/oauth/token', {
      grant_type: 'refresh_token',
      client_id: ML_CLIENT_ID,
      client_secret: ML_CLIENT_SECRET,
      refresh_token: account.refresh_token
    })
    await sb.from('ml_accounts').update({
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      expires_at: new Date(Date.now() + data.expires_in * 1000).toISOString()
    }).eq('ml_user_id', account.ml_user_id)
    return data.access_token
  } catch (e) {
    return account.access_token
  }
}

async function getToken(account) {
  if (!account.expires_at) return account.access_token
  if (new Date(account.expires_at) < new Date(Date.now() + 5 * 60 * 1000)) {
    return await refreshToken(account)
  }
  return account.access_token
}

// ── Detectar tipo via /shipments/{id} ─────────────────────────────
function isFulfillment(shipment) {
  const logistic = (shipment?.logistic_type || '').toLowerCase()
  const tags     = shipment?.tags || []
  if (logistic === 'fulfillment') return true
  if (tags.includes('meli_fulfillment')) return true
  return false
}

async function detectOrderType(order, token) {
  const tags = order.tags || []
  const shippingLogistic = (order.shipping?.logistic_type || '').toLowerCase()

  if (tags.includes('meli_fulfillment')) return 'FULL'
  if (shippingLogistic === 'fulfillment') return 'FULL'
  if (shippingLogistic === 'self_service') return 'FLEX'
  if (shippingLogistic === 'drop_off') return 'NORMAL'

  const shipmentId = order.shipping?.id
  if (shipmentId && token) {
    try {
      const { data: shipment } = await axios.get(
        `https://api.mercadolibre.com/shipments/${shipmentId}`,
        { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
      )
      const logistic = (shipment.logistic_type || '').toLowerCase()
      console.log(`  Shipment ${shipmentId}: logistic=${logistic} tags=${(shipment.tags||[]).join(',')}`)
      if (isFulfillment(shipment)) return 'FULL'
      if (logistic === 'self_service') return 'FLEX'
      return 'NORMAL'
    } catch (e) {
      console.log(`  Shipment ${shipmentId} lookup failed: ${e.message}`)
    }
  }
  return 'NORMAL'
}

// ── Calcular frete líquido real ────────────────────────────────────
// O vendedor paga apenas a diferença entre o custo total do frete
// e o que o comprador pagou de frete
// base_cost = o que o comprador paga de frete
// list_cost = custo total do frete (vendedor + comprador)
// freteVendedor = list_cost - base_cost
async function calcShippingCost(shipmentId, token) {
  if (!shipmentId || !token) return { freteVendedor: 0, freteComprador: 0, freteBruto: 0 }
  try {
    const { data: shipData } = await axios.get(
      `https://api.mercadolibre.com/shipments/${shipmentId}`,
      { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
    )

    // Custo total cobrado do frete (vendedor + comprador)
    const freteBruto = shipData.shipping_option?.list_cost ||
                       shipData.cost_components?.ratio ||
                       shipData.base_cost || 0

    // O que o comprador pagou de frete
    const freteComprador = shipData.base_cost || 0

    // O que o VENDEDOR realmente paga = diferença
    const freteVendedor = Math.max(0, freteBruto - freteComprador)

    console.log(`  Frete shipment ${shipmentId}: bruto=${freteBruto} comprador=${freteComprador} vendedor=${freteVendedor}`)
    return { freteVendedor, freteComprador, freteBruto }
  } catch (e) {
    console.log(`  Erro frete shipment ${shipmentId}: ${e.message}`)
    return { freteVendedor: 0, freteComprador: 0, freteBruto: 0 }
  }
}

// ── Sync ──────────────────────────────────────────────────────────
async function syncMLOrders(account) {
  try {
    const token = await getToken(account)
    let totalNew = 0

    const dateFrom = new Date()
    dateFrom.setDate(dateFrom.getDate() - 30)
    const dateFromStr = dateFrom.toISOString().slice(0, 19) + '.000-00:00'

    for (const mlStatus of ['paid', 'payment_in_process']) {
      let offset = 0
      let hasMore = true

      while (hasMore) {
        try {
          const { data } = await axios.get(
            `https://api.mercadolibre.com/orders/search?seller=${account.ml_user_id}&order.status=${mlStatus}&order.date_created.from=${encodeURIComponent(dateFromStr)}&sort=date_desc&limit=50&offset=${offset}`,
            { headers: { Authorization: `Bearer ${token}` } }
          )

          const results = data.results || []
          const total = data.paging?.total || 0

          for (const order of results) {
            const { data: existing } = await sb.from('ml_orders')
              .select('id').eq('ml_order_id', String(order.id)).maybeSingle()
            if (existing) continue

            const orderType = await detectOrderType(order, token)
            const isFull = orderType === 'FULL'
            const status = isFull ? 'full_ml' : 'aguardando'

            const items = order.order_items.map(item => ({
              sku: item.item.seller_sku || item.item.id,
              name: item.item.title,
              qty: item.quantity,
              ml_item_id: item.item.id,
              thumbnail: item.item.thumbnail
            }))

            const saleFeeTot = order.order_items?.reduce((s,i) => s + (i.sale_fee || 0), 0) || 0
            const taxesAmount = order.taxes?.amount || 0
            const shipmentId = order.shipping?.id ? String(order.shipping.id) : null

            // ✅ CORREÇÃO: salvar frete líquido do vendedor
            const { freteVendedor, freteComprador, freteBruto } = await calcShippingCost(shipmentId, token)

            // paid_amount = o que realmente cai na conta do vendedor
            // total_amount - sale_fee - freteVendedor
            const totalAmount = order.total_amount || 0
            const paidAmount = totalAmount - saleFeeTot - freteVendedor

            await sb.from('ml_orders').insert({
              ml_order_id: String(order.id),
              account_nickname: account.nickname,
              buyer_name: order.buyer?.nickname || order.buyer?.full_name || 'Cliente',
              status,
              order_type: orderType,
              is_fulfillment: isFull,
              items,
              ml_status: mlStatus,
              shipment_id: shipmentId,
              tracking_number: null,
              created_at_ml: order.date_created,
              total_amount: totalAmount,
              paid_amount: paidAmount,
              sale_fee: saleFeeTot,
              shipping_cost_ml: freteVendedor, // ✅ frete líquido do vendedor
              taxes_amount: taxesAmount
            })

            // Auto cadastra produto (apenas nao-FULL)
            if (!isFull) {
              for (const item of items) {
                if (item.sku) {
                  await sb.from('products').upsert({
                    sku: String(item.sku),
                    name: item.name,
                    description: `ML - ${account.nickname}`,
                    photo: item.thumbnail ? item.thumbnail.replace('-I.jpg', '-O.jpg').replace('http://', 'https://') : null,
                    active: true,
                    source: 'mercadolivre'
                  }, { onConflict: 'sku', ignoreDuplicates: true })
                }
              }
            }
            totalNew++
          }

          if (results.length < 50 || offset + 50 >= total) {
            hasMore = false
          } else {
            offset += 50
            if (offset >= 500) hasMore = false
          }
        } catch (e) {
          console.error(`Erro offset=${offset}:`, e.message)
          hasMore = false
        }
      }
    }

    if (totalNew > 0) console.log(`✅ ${account.nickname}: ${totalNew} novos pedidos`)
    return totalNew
  } catch (e) {
    console.error(`Sync error (${account.nickname}):`, e.response?.data || e.message)
    return 0
  }
}

async function syncAll() {
  const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
  if (!accounts?.length) return
  for (const acc of accounts) await syncMLOrders(acc)
}

// ── Reclassificar pedidos ─────────────────────────────────────────
async function reclassifyOrders() {
  const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
  if (!accounts?.length) return

  const { data: orders } = await sb.from('ml_orders')
    .select('id, ml_order_id, shipment_id, order_type, status')
    .in('status', ['aguardando', 'separando', 'conferindo', 'full_ml'])
    .not('shipment_id', 'is', null)
    .limit(100)

  if (!orders?.length) return

  const account = accounts[0]
  const token = await getToken(account)
  let fixed = 0

  for (const order of orders) {
    try {
      const { data: shipment } = await axios.get(
        `https://api.mercadolibre.com/shipments/${order.shipment_id}`,
        { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
      )

      const logistic = (shipment.logistic_type || '').toLowerCase()
      let correctType = 'NORMAL'
      if (isFulfillment(shipment)) correctType = 'FULL'
      else if (logistic === 'self_service') correctType = 'FLEX'

      if (correctType !== order.order_type) {
        const newStatus = correctType === 'FULL' ? 'full_ml' : 'aguardando'
        await sb.from('ml_orders').update({
          order_type: correctType,
          is_fulfillment: correctType === 'FULL',
          status: newStatus,
          updated_at: new Date().toISOString()
        }).eq('id', order.id)
        fixed++
        console.log(`🔄 Reclassificado ${order.ml_order_id}: ${order.order_type} -> ${correctType}`)
      }
    } catch (e) {}
  }

  if (fixed > 0) console.log(`✅ Reclassificados ${fixed} pedidos`)
}

// ── Verificar entregas ────────────────────────────────────────────
async function checkDeliveries() {
  const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
  if (!accounts?.length) return

  const { data: orders } = await sb.from('ml_orders')
    .select('id, ml_order_id, shipment_id, status, order_type, tracking_number')
    .in('status', ['embalado', 'aguardando', 'separando', 'conferindo', 'full_ml'])
    .not('shipment_id', 'is', null)
    .limit(100)

  if (!orders?.length) return

  const account = accounts[0]
  const token = await getToken(account)
  let delivered = 0

  for (const order of orders) {
    try {
      const { data: shipment } = await axios.get(
        `https://api.mercadolibre.com/shipments/${order.shipment_id}`,
        { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
      )

      const shipStatus = (shipment.status || '').toLowerCase()
      const entregue = ['delivered', 'delivered_to_neighbor'].includes(shipStatus)

      if (entregue && order.status !== 'finalizado') {
        await sb.from('ml_orders').update({
          status: 'finalizado',
          tracking_number: shipment.tracking_number || order.tracking_number || null,
          updated_at: new Date().toISOString()
        }).eq('id', order.id)
        delivered++
        console.log(`📦 Entregue: ${order.ml_order_id}`)
      }

      if (!order.tracking_number && shipment.tracking_number) {
        await sb.from('ml_orders').update({
          tracking_number: shipment.tracking_number,
          updated_at: new Date().toISOString()
        }).eq('id', order.id)
      }
    } catch (e) {}
  }

  if (delivered > 0) console.log(`✅ ${delivered} pedidos finalizados`)
}

// ── Sync Perguntas ML ─────────────────────────────────────────────
async function syncPerguntas() {
  try {
    const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
    if (!accounts?.length) return
    let total = 0
    for (const account of accounts) {
      const token = await getToken(account)
      if (!token) continue
      try {
        const { data: resp } = await axios.get(
          `https://api.mercadolibre.com/my/questions/search?status=UNANSWERED&limit=20`,
          { headers: { Authorization: `Bearer ${token}` }, timeout: 8000 }
        )
        const perguntas = resp?.questions || []
        for (const p of perguntas) {
          const { data: item } = await axios.get(
            `https://api.mercadolibre.com/items/${p.item_id}?attributes=title`,
            { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
          ).catch(() => ({ data: null }))

          await sb.from('ml_perguntas').upsert({
            pergunta_id: String(p.id),
            account_nickname: account.nickname,
            comprador: p.from?.nickname || 'Cliente',
            texto: p.text,
            item_id: p.item_id,
            item_titulo: item?.title || p.item_id,
            status: 'pendente',
            created_at: p.date_created,
            synced_at: new Date().toISOString()
          }, { onConflict: 'pergunta_id', ignoreDuplicates: false })
          total++
        }
      } catch (e) {
        console.log(`Erro perguntas ${account.nickname}: ${e.message}`)
      }
    }
    if (total > 0) console.log(`💬 ${total} perguntas sincronizadas`)
  } catch (e) {
    console.log('Erro sync perguntas:', e.message)
  }
}

// ── Sync Estoque ML ───────────────────────────────────────────────
async function syncEstoqueML() {
  try {
    const { data: prods } = await sb.from('products').select('id,ml_item_id,sku').not('ml_item_id', 'is', null)
    if (!prods?.length) return
    const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
    if (!accounts?.length) return
    const token = await getToken(accounts[0])
    if (!token) return

    for (const prod of prods) {
      try {
        const { data: item } = await axios.get(
          `https://api.mercadolibre.com/items/${prod.ml_item_id}`,
          { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
        )
        const estoque = item.available_quantity || 0
        await sb.from('products').update({ estoque_atual: estoque, updated_at: new Date().toISOString() }).eq('id', prod.id)
        await new Promise(r => setTimeout(r, 200))
      } catch (e) {
        console.log(`Erro estoque ${prod.sku}: ${e.message}`)
      }
    }
    console.log('✅ Sync estoque ML concluído')
  } catch (e) {
    console.log('Erro sync estoque:', e.message)
  }
}

// ── Crons ─────────────────────────────────────────────────────────
cron.schedule('*/2 * * * *', syncAll)
cron.schedule('*/30 * * * *', syncEstoqueML)
cron.schedule('*/15 * * * *', checkDeliveries)
cron.schedule('*/5 * * * *', syncPerguntas)

// ── Webhook ML ────────────────────────────────────────────────────
app.post('/ml/notifications', async (req, res) => {
  res.status(200).json({ ok: true })
  try {
    const { resource, topic, user_id } = req.body
    if (topic !== 'shipments' && topic !== 'orders_v2') return
    const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
    if (!accounts?.length) return
    const account = accounts.find(a => String(a.ml_user_id) === String(user_id)) || accounts[0]
    const token = await getToken(account)

    if (topic === 'shipments' && resource) {
      const shipmentId = resource.split('/').pop()
      if (!shipmentId) return
      const { data: shipment } = await axios.get(
        `https://api.mercadolibre.com/shipments/${shipmentId}`,
        { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
      )
      if ((shipment.status || '').toLowerCase() === 'delivered') {
        const { data: order } = await sb.from('ml_orders')
          .select('id, ml_order_id, status')
          .eq('shipment_id', String(shipmentId))
          .maybeSingle()
        if (order && order.status !== 'finalizado') {
          await sb.from('ml_orders').update({
            status: 'finalizado',
            tracking_number: shipment.tracking_number || null,
            updated_at: new Date().toISOString()
          }).eq('id', order.id)
          console.log(`🎉 Webhook: pedido ${order.ml_order_id} finalizado`)
        }
      }
    }

    if (topic === 'orders_v2' && resource) {
      const orderId = resource.split('/').pop()
      const { data: mlOrder } = await axios.get(
        `https://api.mercadolibre.com/orders/${orderId}`,
        { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
      )
      if (mlOrder.status === 'cancelled') {
        const { data: order } = await sb.from('ml_orders')
          .select('id, status')
          .eq('ml_order_id', String(orderId))
          .maybeSingle()
        if (order && !['finalizado', 'cancelado'].includes(order.status)) {
          await sb.from('ml_orders').update({
            status: 'cancelado',
            updated_at: new Date().toISOString()
          }).eq('id', order.id)
        }
      }
    }
  } catch (e) {
    console.error('Webhook error:', e.message)
  }
})

// ── Endpoints ─────────────────────────────────────────────────────
app.post('/api/sync-perguntas', async (req, res) => {
  res.json({ ok: true })
  syncPerguntas()
})

app.post('/api/pergunta-respondida/:id', async (req, res) => {
  await sb.from('ml_perguntas').update({
    status: 'respondido',
    respondido_at: new Date().toISOString()
  }).eq('pergunta_id', req.params.id)
  res.json({ ok: true })
})

app.post('/api/check-deliveries', async (req, res) => {
  await checkDeliveries()
  res.json({ ok: true })
})

app.post('/api/sync-estoque', async (req, res) => {
  res.json({ ok: true })
  syncEstoqueML()
})

// ✅ NOVO: Recalcular frete de pedidos existentes com o novo cálculo correto
app.post('/api/recalcular-frete', async (req, res) => {
  res.json({ ok: true, message: 'Recalculando frete em background...' })
  ;(async () => {
    const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
    if (!accounts?.length) return
    const token = await getToken(accounts[0])

    const { data: orders } = await sb.from('ml_orders')
      .select('id, ml_order_id, shipment_id, total_amount, sale_fee, shipping_cost_ml, paid_amount')
      .not('shipment_id', 'is', null)
      .limit(500)

    if (!orders?.length) return
    let fixed = 0

    for (const order of orders) {
      try {
        const { freteVendedor } = await calcShippingCost(order.shipment_id, token)
        const paidAmount = (order.total_amount || 0) - (order.sale_fee || 0) - freteVendedor

        if (Math.abs(freteVendedor - (order.shipping_cost_ml || 0)) > 0.01) {
          await sb.from('ml_orders').update({
            shipping_cost_ml: freteVendedor,
            paid_amount: paidAmount,
            updated_at: new Date().toISOString()
          }).eq('id', order.id)
          fixed++
          console.log(`💰 Frete corrigido: ${order.ml_order_id} — antes=${order.shipping_cost_ml} depois=${freteVendedor}`)
        }
        await new Promise(r => setTimeout(r, 300))
      } catch (e) {
        console.log(`Erro em ${order.ml_order_id}: ${e.message}`)
      }
    }
    console.log(`✅ Frete recalculado: ${fixed} pedidos corrigidos`)
  })()
})

app.post('/api/recalcular-custos', async (req, res) => {
  res.json({ ok: true, message: 'Recalculando custos em background...' })
  ;(async () => {
    const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
    if (!accounts?.length) return
    const token = await getToken(accounts[0])

    const { data: orders } = await sb.from('ml_orders')
      .select('id, ml_order_id, shipment_id, sale_fee, shipping_cost_ml, total_amount')
      .not('shipment_id', 'is', null)
      .limit(200)

    if (!orders?.length) return
    let fixed = 0

    for (const order of orders) {
      try {
        const { data: mlOrder } = await axios.get(
          `https://api.mercadolibre.com/orders/${order.ml_order_id}`,
          { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
        )
        const saleFeeTot = mlOrder.order_items?.reduce((s, i) => s + (i.sale_fee || 0), 0) || 0
        const taxesAmount = mlOrder.taxes?.amount || 0
        const { freteVendedor } = await calcShippingCost(order.shipment_id, token)
        const totalAmount = mlOrder.total_amount || order.total_amount
        const paidAmount = totalAmount - saleFeeTot - freteVendedor

        await sb.from('ml_orders').update({
          sale_fee: saleFeeTot,
          shipping_cost_ml: freteVendedor,
          paid_amount: paidAmount,
          taxes_amount: taxesAmount,
          total_amount: totalAmount,
          updated_at: new Date().toISOString()
        }).eq('id', order.id)
        fixed++
        await new Promise(r => setTimeout(r, 300))
      } catch (e) {
        console.log(`Erro em ${order.ml_order_id}: ${e.message}`)
      }
    }
    console.log(`✅ Custos recalculados: ${fixed} pedidos`)
  })()
})

app.post('/api/reclassify', async (req, res) => {
  await reclassifyOrders()
  res.json({ ok: true })
})

app.post('/api/reclassify-all', async (req, res) => {
  res.json({ ok: true, message: 'Reclassificação em massa iniciada...' })
  ;(async () => {
    const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
    if (!accounts?.length) return
    const { data: orders } = await sb.from('ml_orders')
      .select('id, ml_order_id, shipment_id, order_type, status')
      .in('status', ['aguardando', 'separando', 'conferindo', 'full_ml', 'embalado'])
      .not('shipment_id', 'is', null)
    if (!orders?.length) return
    const token = await getToken(accounts[0])
    let fixed = 0
    for (const order of orders) {
      try {
        const { data: shipment } = await axios.get(
          `https://api.mercadolibre.com/shipments/${order.shipment_id}`,
          { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
        )
        const logistic = (shipment.logistic_type || '').toLowerCase()
        let correctType = 'NORMAL'
        if (isFulfillment(shipment)) correctType = 'FULL'
        else if (logistic === 'self_service') correctType = 'FLEX'
        if (correctType !== order.order_type) {
          await sb.from('ml_orders').update({
            order_type: correctType,
            is_fulfillment: correctType === 'FULL',
            status: correctType === 'FULL' ? 'full_ml' : 'aguardando',
            updated_at: new Date().toISOString()
          }).eq('id', order.id)
          fixed++
        }
        await new Promise(r => setTimeout(r, 200))
      } catch (e) {}
    }
    console.log(`✅ Reclassificação: ${fixed} corrigidos de ${orders.length}`)
  })()
})

app.get('/', (req, res) => res.json({
  status: '🚀 TMP10 Backend v8.0 — Frete líquido corrigido',
  uptime: Math.floor(process.uptime()) + 's',
  sync_interval: '2 minutos',
  delivery_check: '15 minutos'
}))

app.get('/api/ml/accounts', async (req, res) => {
  const { data } = await sb.from('ml_accounts').select('id,nickname,active,created_at').eq('active', true)
  res.json(data || [])
})

app.get('/api/orders', async (req, res) => {
  const { status, type, limit = 500 } = req.query
  let q = sb.from('ml_orders').select('*').order('created_at_ml', { ascending: false }).limit(Number(limit))
  if (status) q = q.eq('status', status)
  if (type) q = q.eq('order_type', type)
  const { data } = await q
  res.json(data || [])
})

app.patch('/api/orders/:id', async (req, res) => {
  const { data } = await sb.from('ml_orders').update({
    ...req.body,
    updated_at: new Date().toISOString()
  }).eq('id', req.params.id).select().single()
  res.json(data)
})

app.get('/api/sync', async (req, res) => {
  await syncAll()
  const { count } = await sb.from('ml_orders').select('*', { count: 'exact', head: true })
  res.json({ ok: true, total: count })
})

app.post('/api/sync', async (req, res) => {
  await syncAll()
  const { count } = await sb.from('ml_orders').select('*', { count: 'exact', head: true })
  res.json({ ok: true, total: count })
})

app.get('/api/stats', async (req, res) => {
  const { data } = await sb.from('ml_orders').select('status,order_type')
  res.json({
    aguardando: data?.filter(o => o.status === 'aguardando').length || 0,
    separando:  data?.filter(o => o.status === 'separando').length  || 0,
    embalado:   data?.filter(o => o.status === 'embalado').length   || 0,
    conferindo: data?.filter(o => o.status === 'conferindo').length || 0,
    finalizado: data?.filter(o => o.status === 'finalizado').length || 0,
    erro:       data?.filter(o => o.status === 'erro').length       || 0,
    full_ml:    data?.filter(o => o.order_type === 'FULL').length   || 0,
    flex:       data?.filter(o => o.order_type === 'FLEX').length   || 0,
    normal:     data?.filter(o => o.order_type === 'NORMAL').length || 0,
    total:      data?.length || 0
  })
})

app.post('/api/ml/import-products', async (req, res) => {
  const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
  let imported = 0
  for (const acc of accounts || []) {
    try {
      const token = await getToken(acc)
      const { data } = await axios.get(
        `https://api.mercadolibre.com/users/${acc.ml_user_id}/items/search?limit=100`,
        { headers: { Authorization: `Bearer ${token}` } }
      )
      for (const itemId of data.results || []) {
        try {
          const { data: item } = await axios.get(
            `https://api.mercadolibre.com/items/${itemId}`,
            { headers: { Authorization: `Bearer ${token}` } }
          )
          await sb.from('products').upsert({
            sku: String(item.seller_sku || item.id),
            name: item.title,
            photo: item.thumbnail ? item.thumbnail.replace('-I.jpg', '-O.jpg').replace('http://', 'https://') : null,
            active: true,
            source: 'mercadolivre'
          }, { onConflict: 'sku' })
          imported++
        } catch (e) {}
      }
    } catch (e) {}
  }
  res.json({ imported })
})

const PORT = process.env.PORT || 3001
app.listen(PORT, () => {
  console.log(`🚀 TMP10 v8.0 porta ${PORT}`)
  setTimeout(syncAll, 3000)
  setTimeout(reclassifyOrders, 10000)
  setTimeout(checkDeliveries, 20000)
})
