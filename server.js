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

// ── Auth ML ───────────────────────────────────────────────────────
app.get('/ml/auth/:accountId', (req, res) => {
  const redirectUri = `${RAILWAY_URL}/ml/callback`
  const url = `https://auth.mercadolivre.com.br/authorization?response_type=code&client_id=${ML_CLIENT_ID}&redirect_uri=${encodeURIComponent(redirectUri)}&state=${req.params.accountId}`
  res.redirect(url)
})

app.get('/ml/callback', async (req, res) => {
  const { code, state: accountId } = req.query
  const redirectUri = `${RAILWAY_URL}/ml/callback`
  try {
    const { data: tok } = await axios.post('https://api.mercadolibre.com/oauth/token', {
      grant_type: 'authorization_code',
      client_id: ML_CLIENT_ID,
      client_secret: ML_CLIENT_SECRET,
      code,
      redirect_uri: redirectUri
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
    console.error('ML auth error:', e.response?.data || e.message)
    res.redirect(`https://tmp10.com.br?ml_error=true`)
  }
})

// ── Token refresh ─────────────────────────────────────────────────
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
    console.error('Refresh error:', e.message)
    return account.access_token
  }
}

async function getToken(account) {
  if (!account.expires_at) return account.access_token
  const exp = new Date(account.expires_at)
  if (exp < new Date(Date.now() + 5 * 60 * 1000)) return await refreshToken(account)
  return account.access_token
}

// ── Detect if order is FULL/Fulfillment ──────────────────────────
function isFulfillment(order) {
  // Check logistic type
  const logisticType = order.shipping?.logistic_type || ''
  const fulfillmentTypes = ['fulfillment', 'self_service', 'xd_drop_off', 'drop_off']
  
  // If logistic type contains fulfillment = ML embala
  if (fulfillmentTypes.some(t => logisticType.toLowerCase().includes(t))) {
    return true
  }
  
  // Check tags
  const tags = order.tags || []
  if (tags.includes('fulfillment') || tags.includes('meli_fulfillment')) {
    return true
  }

  return false
}

function getOrderType(order) {
  const logisticType = order.shipping?.logistic_type || ''
  if (logisticType.includes('fulfillment')) return 'FULL'
  if (logisticType.includes('flex')) return 'FLEX'
  if (logisticType.includes('self_service')) return 'FULL'
  if (logisticType.includes('xd_drop_off')) return 'FULL'
  return 'NORMAL'
}

// ── Sync ML orders ────────────────────────────────────────────────
async function syncMLOrders(account) {
  try {
    const token = await getToken(account)
    let totalNew = 0

    for (const mlStatus of ['paid', 'payment_in_process']) {
      const { data } = await axios.get(
        `https://api.mercadolibre.com/orders/search/recent?seller=${account.ml_user_id}&order.status=${mlStatus}&limit=200`,
        { headers: { Authorization: `Bearer ${token}` } }
      )

      for (const order of data.results || []) {
        const { data: existing } = await sb.from('ml_orders')
          .select('id').eq('ml_order_id', String(order.id)).maybeSingle()
        if (existing) continue

        const full = isFulfillment(order)
        const orderType = getOrderType(order)

        const items = order.order_items.map(item => ({
          sku: item.item.seller_sku || item.item.id,
          name: item.item.title,
          qty: item.quantity,
          ml_item_id: item.item.id,
          thumbnail: item.item.thumbnail
        }))

        // FULL orders: status = 'full_ml' (ML embala, não aparece na fila)
        // FLEX/NORMAL: status = 'aguardando' (entra na fila de embalagem)
        const status = full ? 'full_ml' : 'aguardando'

        // Get tracking number from shipment
        let trackingNumber = null
        try {
          if (order.shipping?.id) {
            const { data: shipment } = await axios.get(
              `https://api.mercadolibre.com/shipments/${order.shipping.id}`,
              { headers: { Authorization: `Bearer ${token}` } }
            )
            trackingNumber = shipment?.tracking_number || shipment?.tracking_method || String(order.shipping.id)
          }
        } catch(e) {}

        await sb.from('ml_orders').insert({
          ml_order_id: String(order.id),
          account_nickname: account.nickname,
          buyer_name: order.buyer?.nickname || order.buyer?.full_name || 'Cliente',
          status,
          order_type: orderType,
          is_fulfillment: full,
          items,
          ml_status: mlStatus,
          shipment_id: order.shipping?.id ? String(order.shipping.id) : null,
          tracking_number: trackingNumber,
          created_at_ml: order.date_created
        })

        // Auto register products (only for non-full orders)
        if (!full) {
          for (const item of items) {
            if (item.sku) {
              await sb.from('products').upsert({
                sku: String(item.sku),
                name: item.name,
                description: `Importado ML - ${account.nickname}`,
                photo: item.thumbnail ? item.thumbnail.replace('-I.jpg','-O.jpg').replace('http://','https://') : null,
                active: true,
                source: 'mercadolivre'
              }, { onConflict: 'sku', ignoreDuplicates: true })
            }
          }
        }
        totalNew++
      }
    }
    console.log(`✅ ${account.nickname}: ${totalNew} novos pedidos`)
  } catch (e) {
    console.error(`Sync error (${account.nickname}):`, e.response?.data || e.message)
  }
}

async function syncAll() {
  const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
  if (!accounts?.length) return
  console.log(`🔄 Sincronizando ${accounts.length} conta(s)...`)
  for (const acc of accounts) await syncMLOrders(acc)
}

cron.schedule('*/2 * * * *', syncAll)

// ── API Routes ────────────────────────────────────────────────────
app.get('/', (req, res) => res.json({
  status: '🚀 TMP10 Backend v3.0',
  features: ['FULL detection', '200 orders/account', 'Auto sync 2min']
}))

app.get('/api/ml/accounts', async (req, res) => {
  const { data } = await sb.from('ml_accounts').select('id,nickname,active,created_at').eq('active', true)
  res.json(data || [])
})

// Queue - only orders to pack (no FULL)
app.get('/api/orders', async (req, res) => {
  const { status, limit = 200, include_full } = req.query
  let q = sb.from('ml_orders').select('*').order('created_at_ml', { ascending: true }).limit(Number(limit))
  
  // By default exclude FULL orders from queue
  if (!include_full) q = q.neq('status', 'full_ml')
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

app.post('/api/sync', async (req, res) => {
  await syncAll()
  res.json({ ok: true, message: 'Sincronização concluída!' })
})

app.get('/api/stats', async (req, res) => {
  const { data } = await sb.from('ml_orders').select('status, order_type, is_fulfillment')
  const stats = {
    aguardando: data?.filter(o => o.status === 'aguardando').length || 0,
    separando: data?.filter(o => o.status === 'separando').length || 0,
    embalado: data?.filter(o => o.status === 'embalado').length || 0,
    erro: data?.filter(o => o.status === 'erro').length || 0,
    full_ml: data?.filter(o => o.status === 'full_ml').length || 0,
    total: data?.length || 0
  }
  res.json(stats)
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
              item.attributes?.find(a=>a.id==='COLOR')?.value_name,
              item.attributes?.find(a=>a.id==='SIZE')?.value_name
            ].filter(Boolean).join(' | ') || '',
            photo: item.thumbnail ? item.thumbnail.replace('-I.jpg','-O.jpg').replace('http://','https://') : null,
            barcode: item.attributes?.find(a=>a.id==='EAN')?.value_name || null,
            active: true,
            source: 'mercadolivre'
          }, { onConflict: 'sku' })
          imported++
        } catch(e) {}
      }
    } catch (e) { console.error('Import error:', e.message) }
  }
  res.json({ imported, message: `${imported} produtos importados!` })
})

const PORT = process.env.PORT || 3001
app.listen(PORT, () => {
  console.log(`🚀 TMP10 Backend v3.0 na porta ${PORT}`)
  setTimeout(syncAll, 5000)
})
