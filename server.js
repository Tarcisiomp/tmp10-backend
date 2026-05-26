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
  process.env.SUPABASE_SERVICE_KEY || 'sb_secret_AsA000_3nmzAuTQmn_Noaw_gleAikud'
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
// REGRA OFICIAL ML:
//   FULL = logistic_type === 'fulfillment' E enviado pelo CD do ML
//   FLEX = logistic_type === 'self_service'
//   NORMAL = tudo o mais (drop_off, me1, me2, xd_drop_off, etc)
//
// IMPORTANTE: me2 = Mercado Envios 2 = envio NORMAL (não é FULL!)
// FULL só é FULL quando logistic_type === 'fulfillment' explicitamente

function isFulfillment(shipment) {
  const logistic = (shipment?.logistic_type || '').toLowerCase()
  const tags     = shipment?.tags || []

  // Critério 1 — logistic_type explicitamente fulfillment
  if (logistic === 'fulfillment') return true

  // Critério 2 — tag meli_fulfillment (nome oficial da tag do FULL)
  if (tags.includes('meli_fulfillment')) return true

  // Critério 3 — modo me1 + fulfillment juntos (raramente usado)
  // NÃO inclui me2 sozinho — me2 = Mercado Envios 2 = envio normal!

  return false
}

async function detectOrderType(order, token) {
  const tags = order.tags || []
  const shippingLogistic = (order.shipping?.logistic_type || '').toLowerCase()

  // 1. Verifica pelo payload do pedido (rápido)
  // Tag fulfillment no pedido = FULL com certeza
  if (tags.includes('meli_fulfillment')) return 'FULL'

  // logistic_type no payload do pedido
  if (shippingLogistic === 'fulfillment') return 'FULL'
  if (shippingLogistic === 'self_service') return 'FLEX'
  if (shippingLogistic === 'drop_off') return 'NORMAL'
  // NÃO retorna FULL para 'me2' — me2 é envio normal!

  // 2. Consulta /shipments para confirmar (fonte mais confiável)
  const shipmentId = order.shipping?.id
  if (shipmentId && token) {
    try {
      const { data: shipment } = await axios.get(
        `https://api.mercadolibre.com/shipments/${shipmentId}`,
        { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
      )

      const logistic  = (shipment.logistic_type || '').toLowerCase()
      const mode      = (shipment.mode || '').toLowerCase()
      const shipTags  = shipment.tags || []

      console.log(`  Shipment ${shipmentId}: logistic=${logistic} mode=${mode} tags=${shipTags.join(',')}`)

      // FULL — critério rigoroso
      if (isFulfillment(shipment)) return 'FULL'

      // FLEX
      if (logistic === 'self_service') return 'FLEX'

      // NORMAL — tudo o mais (drop_off, me1, me2, xd_drop_off, etc)
      // me2 = Mercado Envios 2 = NORMAL (empresa embala e envia)
      return 'NORMAL'

    } catch (e) {
      console.log(`  Shipment ${shipmentId} lookup failed: ${e.message}`)
    }
  }

  return 'NORMAL'
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

            // Detecta tipo correto (com consulta ao /shipments se necessario)
            const orderType = await detectOrderType(order, token)
            const isFull = orderType === 'FULL'
            const isFlex = orderType === 'FLEX'
            const status = isFull ? 'full_ml' : 'aguardando'

            const items = order.order_items.map(item => ({
              sku: item.item.seller_sku || item.item.id,
              name: item.item.title,
              qty: item.quantity,
              ml_item_id: item.item.id,
              thumbnail: item.item.thumbnail
            }))

            await sb.from('ml_orders').insert({
              ml_order_id: String(order.id),
              account_nickname: account.nickname,
              buyer_name: order.buyer?.nickname || order.buyer?.full_name || 'Cliente',
              status,
              order_type: orderType,
              is_fulfillment: isFull,
              items,
              ml_status: mlStatus,
              shipment_id: order.shipping?.id ? String(order.shipping.id) : null,
              tracking_number: null,
              created_at_ml: order.date_created
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

// Cron a cada 2 minutos
cron.schedule('*/2 * * * *', syncAll)

// ── Reclassificar pedidos NORMAL que deveriam ser FULL/FLEX ───────
// Roda uma vez por hora para corrigir pedidos antigos mal classificados
async function reclassifyOrders() {
  const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
  if (!accounts?.length) return

  // Busca pedidos com shipment_id para verificar classificação
  // Inclui NORMAL (podem ser FULL errados) e FULL (podem ser NORMAL errados)
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

      const logistic  = (shipment.logistic_type || '').toLowerCase()
      const shipTags  = shipment.tags || []

      // Usa a mesma regra rigorosa — me2 NÃO é FULL
      let correctType = 'NORMAL'
      if (isFulfillment(shipment)) {
        correctType = 'FULL'
      } else if (logistic === 'self_service') {
        correctType = 'FLEX'
      }

      if (correctType !== order.order_type) {
        const newStatus = correctType === 'FULL' ? 'full_ml' : 'aguardando'
        await sb.from('ml_orders').update({
          order_type: correctType,
          is_fulfillment: correctType === 'FULL',
          status: newStatus,
          updated_at: new Date().toISOString()
        }).eq('id', order.id)
        fixed++
        console.log(`🔄 Reclassificado ${order.ml_order_id}: ${order.order_type} -> ${correctType} (logistic=${logistic})`)
      }
    } catch (e) {
      // ignora erros individuais
    }
  }

  if (fixed > 0) console.log(`✅ Reclassificados ${fixed} pedidos`)
  else console.log('✅ Todos os pedidos já estão classificados corretamente')
}

// ── Verificar entregas — dá baixa automática ──────
// Consulta o status do shipment no ML e finaliza pedidos entregues
async function checkDeliveries() {
  const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
  if (!accounts?.length) return

  // Busca pedidos embalados ou aguardando/separando que têm shipment_id
  // (pedidos que já saíram mas podem ter sido entregues direto pelo ML)
  const { data: orders } = await sb.from('ml_orders')
    .select('id, ml_order_id, shipment_id, status, order_type')
    .in('status', ['embalado', 'aguardando', 'separando', 'conferindo', 'full_ml'])
    .not('shipment_id', 'is', null)
    .limit(100)

  if (!orders?.length) return

  const account = accounts[0]
  const token = await getToken(account)
  let delivered = 0
  let cancelled = 0

  for (const order of orders) {
    try {
      // Consulta status do shipment no ML
      const { data: shipment } = await axios.get(
        `https://api.mercadolibre.com/shipments/${order.shipment_id}`,
        { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
      )

      const shipStatus = (shipment.status || '').toLowerCase()
      const substatus  = (shipment.substatus || '').toLowerCase()

      // Status de entregue no ML
      const entregue = [
        'delivered',      // entregue
        'delivered_to_neighbor', // entregue ao vizinho
      ].includes(shipStatus)

      // Cancelado/devolvido no ML
      const cancelado = [
        'cancelled',
        'not_delivered',
        'returned',
        'lost'
      ].includes(shipStatus)

      if (entregue && order.status !== 'finalizado') {
        await sb.from('ml_orders').update({
          status: 'finalizado',
          tracking_number: shipment.tracking_number || order.tracking_number || null,
          updated_at: new Date().toISOString()
        }).eq('id', order.id)
        delivered++
        console.log(`📦 Entregue: ${order.ml_order_id} (${shipStatus})`)
      }

      // Também atualiza tracking_number se não tiver
      if (!order.tracking_number && shipment.tracking_number) {
        await sb.from('ml_orders').update({
          tracking_number: shipment.tracking_number,
          updated_at: new Date().toISOString()
        }).eq('id', order.id)
      }

    } catch (e) {
      // ignora erros individuais (token expirado, shipment não encontrado)
    }
  }

  if (delivered > 0) console.log(`✅ ${delivered} pedidos finalizados automaticamente`)
  if (cancelled > 0) console.log(`❌ ${cancelled} pedidos cancelados pelo ML`)
}

// Verifica entregas a cada 15 minutos
cron.schedule('*/15 * * * *', checkDeliveries)

// ── Webhook do ML — recebe notificações em tempo real ─
// Quando o ML entrega um pedido, ele notifica esta rota
app.post('/ml/notifications', async (req, res) => {
  // Responde 200 imediatamente (ML exige resposta rápida)
  res.status(200).json({ ok: true })

  try {
    const { resource, topic, user_id } = req.body
    console.log(`📩 Notificação ML: topic=${topic}, resource=${resource}`)

    // Só processa notificações de shipments (entregas)
    if (topic !== 'shipments' && topic !== 'orders_v2') return

    const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
    if (!accounts?.length) return

    const account = accounts.find(a => String(a.ml_user_id) === String(user_id)) || accounts[0]
    const token = await getToken(account)

    if (topic === 'shipments' && resource) {
      // Extrai o shipment_id da URL do resource
      const shipmentId = resource.split('/').pop()
      if (!shipmentId) return

      const { data: shipment } = await axios.get(
        `https://api.mercadolibre.com/shipments/${shipmentId}`,
        { headers: { Authorization: `Bearer ${token}` }, timeout: 5000 }
      )

      const shipStatus = (shipment.status || '').toLowerCase()

      if (shipStatus === 'delivered') {
        // Busca o pedido pelo shipment_id
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
          console.log(`🎉 Webhook: pedido ${order.ml_order_id} finalizado (entregue)`)
        }
      }
    }

    if (topic === 'orders_v2' && resource) {
      // Verifica se o pedido foi cancelado no ML
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

        if (order && !['finalizado','cancelado'].includes(order.status)) {
          await sb.from('ml_orders').update({
            status: 'cancelado',
            updated_at: new Date().toISOString()
          }).eq('id', order.id)
          console.log(`🚫 Webhook: pedido ${orderId} cancelado no ML`)
        }
      }
    }
  } catch (e) {
    console.error('Webhook error:', e.message)
  }
})

// Rota para forçar verificação de entregas manualmente
app.post('/api/check-deliveries', async (req, res) => {
  await checkDeliveries()
  res.json({ ok: true, message: 'Verificação de entregas executada!' })
})


app.get('/', (req, res) => res.json({
  status: '🚀 TMP10 Backend v7.0',
  uptime: Math.floor(process.uptime()) + 's',
  sync_interval: '2 minutos',
  reclassify_interval: '1 hora',
  delivery_check_interval: '15 minutos',
  webhook: '/ml/notifications'
}))

app.get('/api/ml/accounts', async (req, res) => {
  const { data } = await sb.from('ml_accounts')
    .select('id,nickname,active,created_at').eq('active', true)
  res.json(data || [])
})

app.get('/api/orders', async (req, res) => {
  const { status, type, limit = 500 } = req.query
  let q = sb.from('ml_orders').select('*')
    .order('created_at_ml', { ascending: false })
    .limit(Number(limit))
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
  const { count } = await sb.from('ml_orders')
    .select('*', { count: 'exact', head: true })
  res.json({ ok: true, total: count, message: 'Sincronizado!' })
})

app.post('/api/sync', async (req, res) => {
  await syncAll()
  const { count } = await sb.from('ml_orders')
    .select('*', { count: 'exact', head: true })
  res.json({ ok: true, total: count, message: 'Sincronizado!' })
})

// Rota para forçar reclassificacao manual
app.post('/api/reclassify', async (req, res) => {
  await reclassifyOrders()
  res.json({ ok: true, message: 'Reclassificacao executada!' })
})

// Rota para reclassificar TODOS os pedidos (sem limite)
app.post('/api/reclassify-all', async (req, res) => {
  res.json({ ok: true, message: 'Reclassificação em massa iniciada em background...' })

  // Roda em background sem bloquear a resposta
  ;(async () => {
    const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
    if (!accounts?.length) return

    const { data: orders } = await sb.from('ml_orders')
      .select('id, ml_order_id, shipment_id, order_type, status')
      .in('status', ['aguardando', 'separando', 'conferindo', 'full_ml', 'embalado'])
      .not('shipment_id', 'is', null)

    if (!orders?.length) { console.log('Nenhum pedido para reclassificar'); return }

    console.log(`🔄 Reclassificando ${orders.length} pedidos...`)
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
          console.log(`🔄 ${order.ml_order_id}: ${order.order_type} → ${correctType}`)
        }
        // Pausa pequena para não sobrecarregar a API do ML
        await new Promise(r => setTimeout(r, 200))
      } catch (e) {}
    }
    console.log(`✅ Reclassificação em massa: ${fixed} pedidos corrigidos de ${orders.length}`)
  })()
})

// Rota para corrigir um pedido especifico pelo ml_order_id
app.post('/api/fix-order/:mlOrderId', async (req, res) => {
  const { mlOrderId } = req.params
  const { accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
  const account = accounts?.[0]
  if (!account) return res.status(400).json({ error: 'Nenhuma conta ML ativa' })

  const token = await getToken(account)

  try {
    // Busca o pedido no banco
    const { data: order } = await sb.from('ml_orders')
      .select('*').eq('ml_order_id', mlOrderId).maybeSingle()
    if (!order) return res.status(404).json({ error: 'Pedido nao encontrado' })

    if (!order.shipment_id) return res.status(400).json({ error: 'Pedido sem shipment_id' })

    const { data: shipment } = await axios.get(
      `https://api.mercadolibre.com/shipments/${order.shipment_id}`,
      { headers: { Authorization: `Bearer ${token}` } }
    )

    const logistic = (shipment.logistic_type || '').toLowerCase()

    // Usa regra rigorosa — me2 NÃO é FULL
    let newType = 'NORMAL'
    if (isFulfillment(shipment)) newType = 'FULL'
    else if (logistic === 'self_service') newType = 'FLEX'

    await sb.from('ml_orders').update({
      order_type: newType,
      is_fulfillment: newType === 'FULL',
      status: newType === 'FULL' ? 'full_ml' : order.status,
      updated_at: new Date().toISOString()
    }).eq('id', order.id)

    res.json({
      ok: true,
      ml_order_id: mlOrderId,
      old_type: order.order_type,
      new_type: newType,
      logistic_type: shipment.logistic_type,
      tags: shipTags
    })
  } catch (e) {
    res.status(500).json({ error: e.message })
  }
})

app.get('/api/stats', async (req, res) => {
  const { data } = await sb.from('ml_orders').select('status,order_type')
  res.json({
    aguardando:  data?.filter(o => o.status === 'aguardando').length  || 0,
    separando:   data?.filter(o => o.status === 'separando').length   || 0,
    embalado:    data?.filter(o => o.status === 'embalado').length    || 0,
    conferindo:  data?.filter(o => o.status === 'conferindo').length  || 0,
    finalizado:  data?.filter(o => o.status === 'finalizado').length  || 0,
    erro:        data?.filter(o => o.status === 'erro').length        || 0,
    full_ml:     data?.filter(o => o.order_type === 'FULL').length    || 0,
    flex:        data?.filter(o => o.order_type === 'FLEX').length    || 0,
    normal:      data?.filter(o => o.order_type === 'NORMAL').length  || 0,
    total:       data?.length || 0
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
            description: [
              item.attributes?.find(a => a.id === 'COLOR')?.value_name,
              item.attributes?.find(a => a.id === 'SIZE')?.value_name
            ].filter(Boolean).join(' | ') || '',
            photo: item.thumbnail ? item.thumbnail.replace('-I.jpg', '-O.jpg').replace('http://', 'https://') : null,
            barcode: item.attributes?.find(a => a.id === 'EAN')?.value_name || null,
            active: true,
            source: 'mercadolivre'
          }, { onConflict: 'sku' })
          imported++
        } catch (e) {}
      }
    } catch (e) {}
  }
  res.json({ imported, message: `${imported} produtos importados!` })
})

const PORT = process.env.PORT || 3001
app.listen(PORT, () => {
  console.log(`🚀 TMP10 v7.0 porta ${PORT}`)
  setTimeout(syncAll, 3000)
  setTimeout(reclassifyOrders, 10000)
  setTimeout(checkDeliveries, 20000) // verifica entregas 20s após iniciar
})
