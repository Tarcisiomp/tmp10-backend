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

// ── Order type ────────────────────────────────────────────────────
function getOrderType(order) {
  const logistic = (order.shipping?.logistic_type || '').toLowerCase()
  const tags = order.tags || []
  if (
    logistic.includes('fulfillment') ||
    logistic.includes('self_service') ||
    logistic.includes('xd_drop_off') ||
    tags.includes('fulfillment') ||
    tags.includes('meli_fulfillment')
  ) return 'FULL'
  if (logistic.includes('flex')) return 'FLEX'
  return 'NORMAL'
}

// ── Sync ──────────────────────────────────────────────────────────
async function syncMLOrders(account) {
  try {
    const token = await getToken(account)
    let totalNew = 0

    // Data de 30 dias atras
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
            // Check if already exists
            const { data: existing } = await sb.from('ml_orders')
              .select('id').eq('ml_order_id', String(order.id)).maybeSingle()
            if (existing) continue

            const orderType = getOrderType(order)
            const isFull = orderType === 'FULL'
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

            // Auto cadastra produto
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

          // Tem mais paginas?
          if (results.length < 50 || offset + 50 >= total) {
            hasMore = false
          } else {
            offset += 50
            if (offset >= 500) hasMore = false // segurança
          }
        } catch (e) {
          console.error(`Erro offset=${offset}:`, e.message)
          hasMore = false
        }
      }
    }

    if (totalNew > 0) {
      console.log(`✅ ${account.nickname}: ${totalNew} novos pedidos`)
    }
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

// Sincroniza a cada 2 minutos
cron.schedule('*/2 * * * *', syncAll)

// ── Routes ────────────────────────────────────────────────────────
app.get('/', (req, res) => res.json({
  status: '🚀 TMP10 Backend v5.0',
  uptime: Math.floor(process.uptime()) + 's',
  sync_interval: '2 minutos'
}))

app.get('/api/ml/accounts', async (req, res) => {
  const { data } = await sb.from('ml_accounts')
    .select('id,nickname,active,created_at').eq('active', true)
  res.json(data || [])
})

app.get('/api/orders', async (req, res) => {
  const { status, limit = 500 } = req.query
  let q = sb.from('ml_orders').select('*')
    .order('created_at_ml', { ascending: false })
    .limit(Number(limit))
  if (status) q = q.eq('status', status)
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

app.get('/api/stats', async (req, res) => {
  const { data } = await sb.from('ml_orders').select('status,order_type')
  res.json({
    aguardando: data?.filter(o => o.status === 'aguardando').length || 0,
    separando: data?.filter(o => o.status === 'separando').length || 0,
    embalado: data?.filter(o => o.status === 'embalado').length || 0,
    erro: data?.filter(o => o.status === 'erro').length || 0,
    full_ml: data?.filter(o => o.status === 'full_ml').length || 0,
    flex: data?.filter(o => o.order_type === 'FLEX').length || 0,
    total: data?.length || 0
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
  console.log(`🚀 TMP10 v5.0 porta ${PORT}`)
  // Sync logo ao iniciar
  setTimeout(syncAll, 3000)
})
