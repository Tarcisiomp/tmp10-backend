require('dotenv').config()
const express = require('express')
const cors = require('cors')
const axios = require('axios')
const cron = require('node-cron')
const { createClient } = require('@supabase/supabase-js')

const app = express()
app.use(cors())
app.use(express.json())

// ── Supabase ──────────────────────────────────────────────────────
const sb = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_KEY)

// ── Mercado Livre Config ──────────────────────────────────────────
const ML_CLIENT_ID     = process.env.ML_CLIENT_ID     || '4022957335913783'
const ML_CLIENT_SECRET = process.env.ML_CLIENT_SECRET || 'f9jB9yc6UvrAnz4kjT6u02xMxjbvn7z3'
const APP_URL          = process.env.APP_URL           || 'https://tmp10.com.br'

// ════════════════════════════════════════════════════════════════
// MERCADO LIVRE — AUTH
// ════════════════════════════════════════════════════════════════

// Step 1: Redirect user to ML login
app.get('/ml/auth/:accountId', (req, res) => {
  const { accountId } = req.params
  const redirectUri = `${APP_URL}/ml/callback`
  const url = `https://auth.mercadolivre.com.br/authorization?response_type=code&client_id=${ML_CLIENT_ID}&redirect_uri=${redirectUri}&state=${accountId}`
  res.redirect(url)
})

// Step 2: ML redirects back with code
app.get('/ml/callback', async (req, res) => {
  const { code, state: accountId } = req.query
  try {
    const { data } = await axios.post('https://api.mercadolibre.com/oauth/token', {
      grant_type: 'authorization_code',
      client_id: ML_CLIENT_ID,
      client_secret: ML_CLIENT_SECRET,
      code,
      redirect_uri: `${APP_URL}/ml/callback`
    })
    // Save tokens to Supabase
    await sb.from('ml_accounts').upsert({
      account_id: accountId,
      ml_user_id: data.user_id,
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      expires_at: new Date(Date.now() + data.expires_in * 1000).toISOString(),
      active: true
    })
    // Get account info
    const { data: userInfo } = await axios.get(`https://api.mercadolibre.com/users/${data.user_id}`, {
      headers: { Authorization: `Bearer ${data.access_token}` }
    })
    await sb.from('ml_accounts').update({ nickname: userInfo.nickname }).eq('ml_user_id', data.user_id)
    res.redirect(`${APP_URL}?ml_connected=true&nickname=${userInfo.nickname}`)
  } catch (e) {
    console.error('ML auth error:', e.message)
    res.redirect(`${APP_URL}?ml_error=true`)
  }
})

// Refresh token
async function refreshMLToken(account) {
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
    }).eq('id', account.id)
    return data.access_token
  } catch (e) {
    console.error('Token refresh error:', e.message)
    return null
  }
}

// Get valid token
async function getValidToken(account) {
  const expiresAt = new Date(account.expires_at)
  if (expiresAt < new Date(Date.now() + 5 * 60 * 1000)) {
    return await refreshMLToken(account)
  }
  return account.access_token
}

// ════════════════════════════════════════════════════════════════
// MERCADO LIVRE — ORDERS
// ════════════════════════════════════════════════════════════════

async function syncMLOrders(account) {
  try {
    const token = await getValidToken(account)
    if (!token) return

    // Get recent orders
    const { data } = await axios.get(`https://api.mercadolibre.com/orders/search/recent?seller=${account.ml_user_id}&order.status=paid`, {
      headers: { Authorization: `Bearer ${token}` }
    })

    for (const order of data.results || []) {
      // Check if order already exists
      const { data: existing } = await sb.from('ml_orders')
        .select('id').eq('ml_order_id', order.id.toString()).single()
      if (existing) continue

      // Get order items
      const items = order.order_items.map(item => ({
        sku: item.item.seller_sku || item.item.id,
        name: item.item.title,
        qty: item.quantity,
        ml_item_id: item.item.id,
        thumbnail: item.item.thumbnail
      }))

      // Save order to Supabase
      await sb.from('ml_orders').insert({
        ml_order_id: order.id.toString(),
        ml_account_id: account.id,
        account_nickname: account.nickname,
        buyer_name: order.buyer?.nickname || 'Cliente',
        status: 'pending',
        items: JSON.stringify(items),
        ml_status: order.status,
        created_at_ml: order.date_created
      })

      // Auto-match products by SKU
      for (const item of items) {
        if (item.sku) {
          const { data: product } = await sb.from('products')
            .select('id').eq('sku', item.sku).single()
          if (!product) {
            // Auto-create product from ML data
            await sb.from('products').upsert({
              sku: item.sku,
              name: item.name,
              description: `Importado do Mercado Livre - ${account.nickname}`,
              photo: item.thumbnail,
              active: true,
              source: 'mercadolivre'
            }, { onConflict: 'sku' })
          }
        }
      }
    }
    console.log(`✅ ML sync: ${account.nickname} - ${data.results?.length || 0} pedidos`)
  } catch (e) {
    console.error(`ML sync error (${account.nickname}):`, e.message)
  }
}

// ════════════════════════════════════════════════════════════════
// SYNC ALL ACCOUNTS — runs every 2 minutes
// ════════════════════════════════════════════════════════════════
async function syncAll() {
  const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
  if (!accounts) return
  for (const account of accounts) {
    await syncMLOrders(account)
  }
}

// Cron job — sync every 2 minutes
cron.schedule('*/2 * * * *', syncAll)

// ════════════════════════════════════════════════════════════════
// API ROUTES
// ════════════════════════════════════════════════════════════════

// Get all connected ML accounts
app.get('/api/ml/accounts', async (req, res) => {
  const { data } = await sb.from('ml_accounts').select('id,nickname,active,created_at').eq('active', true)
  res.json(data || [])
})

// Get orders (all accounts combined)
app.get('/api/orders', async (req, res) => {
  const { status, limit = 50 } = req.query
  let query = sb.from('ml_orders').select('*').order('created_at', { ascending: false }).limit(limit)
  if (status) query = query.eq('status', status)
  const { data } = await query
  res.json(data || [])
})

// Update order status
app.patch('/api/orders/:id', async (req, res) => {
  const { id } = req.params
  const { status, separated_by } = req.body
  const { data } = await sb.from('ml_orders').update({
    status,
    separated_by,
    separated_at: new Date().toISOString()
  }).eq('id', id).select().single()
  res.json(data)
})

// Import products from ML
app.post('/api/ml/import-products', async (req, res) => {
  const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
  let imported = 0
  for (const account of accounts || []) {
    try {
      const token = await getValidToken(account)
      const { data } = await axios.get(`https://api.mercadolibre.com/users/${account.ml_user_id}/items/search?limit=100`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      for (const itemId of data.results || []) {
        const { data: item } = await axios.get(`https://api.mercadolibre.com/items/${itemId}`, {
          headers: { Authorization: `Bearer ${token}` }
        })
        await sb.from('products').upsert({
          sku: item.seller_sku || item.id,
          name: item.title,
          description: `${item.attributes?.find(a=>a.id==='COLOR')?.value_name||''} ${item.attributes?.find(a=>a.id==='SIZE')?.value_name||''}`.trim(),
          photo: item.thumbnail?.replace('-I.jpg', '-O.jpg'),
          barcode: item.attributes?.find(a=>a.id==='EAN')?.value_name,
          active: true,
          source: 'mercadolivre'
        }, { onConflict: 'sku' })
        imported++
      }
    } catch (e) {
      console.error('Import error:', e.message)
    }
  }
  res.json({ imported, message: `${imported} produtos importados!` })
})

// Trigger manual sync
app.post('/api/sync', async (req, res) => {
  await syncAll()
  res.json({ ok: true, message: 'Sincronização concluída!' })
})

// Health check
app.get('/', (req, res) => res.json({ status: 'TMP10 Backend rodando!', version: '1.0.0' }))

const PORT = process.env.PORT || 3001
app.listen(PORT, () => console.log(`🚀 TMP10 Backend rodando na porta ${PORT}`))
