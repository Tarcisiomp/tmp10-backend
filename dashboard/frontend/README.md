# TraderIA WIN — Frontend (trader.tmp10.com.br)

Painel de acompanhamento em um único arquivo (`index.html`, React via CDN),
com login via Supabase Auth, separado do Supabase do TMP10 — projeto novo,
sem misturar usuários ou dados.

## 1. Criar o projeto Supabase (novo, isolado)

1. Acesse [supabase.com](https://supabase.com) e crie um **novo projeto**
   (ex.: `traderia-win`), plano free serve para começar.
2. Em **Authentication → Providers**, confirme que "Email" está habilitado.
3. Em **Authentication → Users**, crie manualmente o seu usuário (ou os
   usuários que vão acompanhar o painel) com e-mail e senha.
4. Em **Project Settings → API**, copie:
   - `Project URL`
   - `anon public key`

## 2. Configurar o `index.html`

Abra `index.html` e edite estas três linhas no topo do bloco `<script>`:

```js
const SUPABASE_URL = "https://SEU-PROJETO.supabase.co";
const SUPABASE_ANON_KEY = "SUA_ANON_KEY_AQUI";
const API_BASE_URL = "https://web-production-XXXXX.up.railway.app";
```

- `SUPABASE_URL` e `SUPABASE_ANON_KEY`: do passo 1.
- `API_BASE_URL`: a URL do backend do TraderIA WIN depois de subir no Railway
  (mesmo processo que você já usa no `tmp10-backend`).

## 3. Liberar o domínio no backend (CORS)

No `main.py` do backend, confirme que `https://trader.tmp10.com.br` está na
lista `allow_origins` do `CORSMiddleware` (já vem configurado por padrão).

## 4. Deploy no Netlify

Sigo o mesmo padrão que você já usa: zipar `index.html` + `sw.js` juntos e
subir como um novo site no Netlify (separado do site do TMP10 principal).

1. Netlify → **Add new site** → **Deploy manually**
2. Arraste o zip com `index.html` e `sw.js`
3. Em **Site settings → Domain management**, adicione o domínio
   `trader.tmp10.com.br`

## 5. Configurar o subdomínio (DNS)

Como `tmp10.com.br` já usa os nameservers da Netlify (Registro.br apontando
pra lá), basta:

1. No painel da Netlify, ir em **Domains** do site principal (tmp10.com.br)
   ou direto nas configurações de DNS da zona `tmp10.com.br`
2. Adicionar um registro `CNAME` (ou "Netlify subdomain") apontando
   `trader` para o site novo que você criou no passo 4
3. Aguardar a propagação (geralmente minutos, pode levar até algumas horas)

## 6. Testar

- Acesse `https://trader.tmp10.com.br`
- Faça login com o usuário criado no passo 1
- O painel deve carregar o status do pregão, operação atual, histórico e
  estatísticas — puxando tudo da API no Railway

## O que o painel mostra

- **Fita de ticker** no topo: últimas decisões da IA (COMPRAR/VENDER/AGUARDAR),
  para automaticamente (fica cinza) fora do horário de pregão (9h–17h45)
- **Status do pregão**: aberto/fechado, horário atual, avisos quando perto
  do fechamento (sem novas operações após 17h30, fechamento forçado após 17h40)
- **Operação atual**: lado, preço de entrada, motivos da decisão
- **Estatísticas**: resultado do dia, últimos 7 e 30 dias, win rate
- **Gestão de risco**: barras mostrando o quanto falta pro stop diário, meta
  diária e limite de operações
- **Histórico**: últimas operações fechadas, com resultado

## Próximos passos possíveis

- Gráfico da curva de capital (hoje só a tabela de histórico)
- Tela de configuração de risco editável direto pelo painel
- WebSocket para atualização em tempo real (hoje o painel atualiza a cada 15s)
