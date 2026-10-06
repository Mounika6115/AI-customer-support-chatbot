# SupportFlow AI — Customer ↔ AI Chatbot Platform

A full-stack e-commerce customer-support system: React/Vite + Flask + relational DB
(SQLite by default, MySQL preferred for production) + JWT + Socket.IO-ready realtime +
grounded Gemini/Mock AI. Pure-AI mode: every question is answered directly by the AI,
no human-agent handoff, no escalation tickets.

## Architecture

```
Customer → Customer Chat UI → AI Chatbot → Gemini / Mock AI
     → Backend API (Flask) → Database (SQLite/MySQL)
```

The AI is the full support layer. Every message gets a direct grounded answer
from verified DB rows (orders, products, returns, refunds, service requests).

## Database (persistent — not localStorage)

All application data lives in the relational DB. `localStorage` holds only the JWT
and display name. Tables (with PKs + FKs):

`users`, `agents`, `product_categories`, `products`, `orders`, `order_items`,
`payments`, `returns`, `refunds`, `conversations`, `messages`, `support_tickets`,
`offers`, `warranties`, `notifications` (+ `knowledge_base`, `agent_notes`,
`feedback`, `evaluation_results`).

Key flows:

- Products: chatbot reads `products`/`product_categories` via `search_products()`,
  `get_product()`, `check_stock()` — Gemini never invents catalogue data.
- Orders: `get_orders()`, `get_order_status()`, `track_order()`, `cancel_order()`
  scoped to the logged-in customer.
- Returns/refunds: `create_return()`, `get_return_status()`, `get_refund_status()`.
- Memory: every customer/AI message is saved in `messages`; the last turns
  are injected into the AI prompt, so "Which one is cheapest?" resolves against
  previously shown products.
- Realtime: Socket.IO rooms (`conversation_<id>`) emit `new_message`
  on every save; the UI also polls every 3 s, so chat updates without refresh.

## Run

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env
python app.py   # http://localhost:5000
```

### MySQL (preferred for production)

```bash
CREATE DATABASE supportdb CHARACTER SET utf8mb4;
# .env:
DATABASE_URL=mysql+pymysql://support:support123@localhost:3306/supportdb
python app.py   # tables are created automatically, then seeded
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

## Demo credentials — development only

- Customer: `customer@example.com` / `Demo123!`
- Admin: `admin@example.com` / `Demo123!`

Try as customer: "Hi" → "Show me Samsung phones under ₹30000" →
"Which one is cheapest?" → "Where is my previous order?" →
"When will I get my refund?" — every question gets a direct AI answer.

## AI providers

`AI_PROVIDER=mock` needs no key. For live answers set `AI_PROVIDER=gemini` and a
real `GEMINI_API_KEY` in `.env` (never in the frontend). The prompt injects only
verified DB rows and instructs the model not to invent facts.

## Production hardening

Before production: Alembic migrations, Redis-backed Socket.IO + rate limits,
refresh-token rotation, CSRF, object storage + malware scan for files, audit logs,
observability, secrets manager, pagination, HTTPS/reverse proxy.
