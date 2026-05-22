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
const sb = createClient(
  process.env.SUPABASE_URL || 'https://foshqdjgbcigggrcjtap.supabase.co',
  process.env.SUPABASE_SERVICE_KEY || 'sb_secret_AsA000_3nmzAuTQmn_Noaw_gleAikud'
)

// ── Mercado Livre Config ──────────────────────────────────────────
const ML_CLIENT_ID     = process.env.ML_CLIENT_ID     || '4022957335913783'
const ML_CLIENT_SECRET = process.env.ML_CLIENT_SECRET || 'f9jB9yc6UvrAnz4kjT6u02xMxjbvn7z3'

// IMPORTANTE: Este é o endereço do seu servidor Railway
const RAILWAY_URL = 'https://web-production-82c10.up.railway.app'

// ── AUTH ──────────────────────────────────────────────────────────

// Step 1: Redirect user to ML login
app.get('/ml/auth/:accountId', (req, res) => {
  const { accountId } = req.params
  const redirectUri = `${RAILWAY_URL}/ml/callback`
  const url = `https://auth.mercadolivre.com.br/authorization?response_type=code&client_id=${ML_CLIENT_ID}&redirect_uri=${encodeURIComponent(redirectUri)}&state=${accountId}`
  res.redirect(url)
})

// Step 2: ML redirects back with code
app.get('/ml/callback', async (req, res) => {
  const { code, state: accountId } = req.query
  const redirectUri = `${RAILWAY_URL}/ml/callback`
  try {
    const { data } = await axios.post('https://api.mercadolibre.com/oauth/token', {
      grant_type: 'authorization_code',
      client_id: ML_CLIENT_ID,
      client_secret: ML_CLIENT_SECRET,
      code,
      redirect_uri: redirectUri
    })

    // Get user info
    const { data: userInfo } = await axios.get(
      `https://api.mercadolibre.com/users/${data.user_id}`,
      { headers: { Authorization: `Bearer ${data.access_token}` } }
    )

    // Save to Supabase
    await sb.from('ml_accounts').upsert({
      account_id: accountId,
      ml_user_id: String(data.user_id),
      nickname: userInfo.nickname,
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      expires_at: new Date(Date.now() + data.expires_in * 1000).toISOString(),
      active: true
    }, { onConflict: 'ml_user_id' })

    // Sync orders immediately
    await syncMLOrders({ ml_user_id: String(data.user_id), access_token: data.access_token, nickname: userInfo.nickname })

    // Redirect back to site with success
    res.redirect(`https://tmp10.com.br?ml_connected=true&nickname=${userInfo.nickname}`)
  } catch (e) {
    console.error('ML auth error:', e.response?.data || e.message)
    res.redirect(`https://tmp10.com.br?ml_error=true&msg=${encodeURIComponent(e.message)}`)
  }
})

// ── Token refresh ────────────────────────────────────────────────
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
    console.error('Refresh token error:', e.message)
    return account.access_token
  }
}

async function getToken(account) {
  if (!account.expires_at) return account.access_token
  const exp = new Date(account.expires_at)
  if (exp < new Date(Date.now() + 5 * 60 * 1000)) {
    return await refreshToken(account)
  }
  return account.access_token
}

// ── Sync orders from ML ──────────────────────────────────────────
async function syncMLOrders(account) {
  try {
    const token = await getToken(account)
    const { data } = await axios.get(
      `https://api.mercadolibre.com/orders/search/recent?seller=${account.ml_user_id}&order.status=paid&limit=50`,
      { headers: { Authorization: `Bearer ${token}` } }
    )

    for (const order of data.results || []) {
      // Check if already exists
      const { data: existing } = await sb.from('ml_orders')
        .select('id').eq('ml_order_id', String(order.id)).maybeSingle()
      if (existing) continue

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
        buyer_name: order.buyer?.nickname || 'Cliente',
        status: 'pending',
        items: items,
        ml_status: order.status,
        created_at_ml: order.date_created
      })

      // Auto-register products
      for (const item of items) {
        if (item.sku) {
          await sb.from('products').upsert({
            sku: String(item.sku),
            name: item.name,
            description: `Importado do ML - ${account.nickname}`,
            photo: item.thumbnail?.replace('-I.jpg','-O.jpg') || null,
            active: true,
            source: 'mercadolivre'
          }, { onConflict: 'sku', ignoreDuplicates: true })
        }
      }
    }
    console.log(`✅ Synced ${account.nickname}: ${data.results?.length || 0} orders`)
  } catch (e) {
    console.error(`Sync error (${account.nickname}):`, e.response?.data || e.message)
  }
}

// ── Sync all accounts every 2 minutes ────────────────────────────
async function syncAll() {
  const { data: accounts } = await sb.from('ml_accounts').select('*').eq('active', true)
  if (!accounts?.length) return
  for (const acc of accounts) await syncMLOrders(acc)
}

cron.schedule('*/2 * * * *', syncAll)

// ── API Routes ────────────────────────────────────────────────────

app.get('/', (req, res) => res.json({
  status: 'TMP10 Backend rodando! 🚀',
  version: '1.0.0',
  railway_url: RAILWAY_URL
}))

app.get('/api/ml/accounts', async (req, res) => {
  const { data } = await sb.from('ml_accounts').select('id,nickname,active,created_at').eq('active', true)
  res.json(data || [])
})

app.get('/api/orders', async (req, res) => {
  const { status, limit = 100 } = req.query
  let q = sb.from('ml_orders').select('*').order('created_at', { ascending: false }).limit(Number(limit))
  if (status) q = q.eq('status', status)
  const { data } = await q
  res.json(data || [])
})

app.patch('/api/orders/:id', async (req, res) => {
  const { data } = await sb.from('ml_orders').update({
    ...req.body,
    separated_at: new Date().toISOString()
  }).eq('id', req.params.id).select().single()
  res.json(data)
})

app.post('/api/sync', async (req, res) => {
  await syncAll()
  res.json({ ok: true, message: 'Sincronização concluída!' })
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
        const { data: item } = await axios.get(
          `https://api.mercadolibre.com/items/${itemId}`,
          { headers: { Authorization: `Bearer ${token}` } }
        )
        const sku = item.seller_sku || item.id
        await sb.from('products').upsert({
          sku: String(sku),
          name: item.title,
          description: [
            item.attributes?.find(a=>a.id==='COLOR')?.value_name,
            item.attributes?.find(a=>a.id==='SIZE')?.value_name
          ].filter(Boolean).join(' | ') || '',
          photo: item.thumbnail?.replace('-I.jpg','-O.jpg') || null,
          barcode: item.attributes?.find(a=>a.id==='EAN')?.value_name || null,
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

const PORT = process.env.PORT || 3001
app.listen(PORT, () => console.log(`🚀 TMP10 Backend na porta ${PORT}`))
