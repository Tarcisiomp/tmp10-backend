-- Tabela de contas ML conectadas
CREATE TABLE ml_accounts (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  account_id text,
  ml_user_id text UNIQUE NOT NULL,
  nickname text,
  access_token text NOT NULL,
  refresh_token text NOT NULL,
  expires_at timestamptz NOT NULL,
  active boolean DEFAULT true,
  created_at timestamptz DEFAULT now()
);

-- Tabela de pedidos ML
CREATE TABLE ml_orders (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  ml_order_id text UNIQUE NOT NULL,
  ml_account_id uuid REFERENCES ml_accounts(id),
  account_nickname text,
  buyer_name text,
  status text DEFAULT 'pending',
  items jsonb,
  ml_status text,
  separated_by text,
  separated_at timestamptz,
  created_at_ml timestamptz,
  created_at timestamptz DEFAULT now()
);

-- Adicionar coluna source na tabela products
ALTER TABLE products ADD COLUMN IF NOT EXISTS source text DEFAULT 'manual';

-- Permissões
ALTER TABLE ml_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE ml_orders ENABLE ROW LEVEL SECURITY;
CREATE POLICY "all" ON ml_accounts FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "all" ON ml_orders FOR ALL USING (true) WITH CHECK (true);
