import React, { useEffect, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./services/api";
import "./styles.css";

const demo = {
  customer: ["customer@example.com", "Demo123!"],
  admin: ["admin@example.com", "Demo123!"],
};

function Login({ setUser }) {
  const [email, setEmail] = useState(demo.customer[0]);
  const [password, setPassword] = useState(demo.customer[1]);
  async function go(e) {
    e.preventDefault();
    try {
      let d = await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      localStorage.setItem("token", d.token);
      localStorage.setItem("user", JSON.stringify(d.user));
      setUser(d.user);
    } catch (e) { alert(e.message); }
  }
  return (
    <div className="login">
      <form onSubmit={go} className="panel">
        <h1>SupportFlow AI</h1>
        <p>AI-powered customer support. Real DB, instant answers.</p>
        <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" />
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" />
        <button>Sign in</button>
        <small>Demo: customer@example.com / Demo123! · admin@example.com / Demo123!</small>
      </form>
    </div>
  );
}

function ProductCards({ products, onClose }) {
  if (!products || !products.length) return null;
  return (
    <div>
      <div className="stackhead"><small>Catalogue results</small><button className="xbtn" onClick={onClose} title="Hide">×</button></div>
    <div className="products">
      {products.map((p) => (
        <div key={p.id} className="product-card">
          <b>{p.product_name || p.name}</b>
          <small>{p.brand} · {p.category}</small>
          <div className="price">₹{p.price} {p.original_price > p.price && <s>₹{p.original_price}</s>}</div>
          <small>⭐ {p.rating} · Stock: {p.stock_quantity} · {p.warranty_period || p.warranty}</small>
        </div>
      ))}
    </div>
    </div>
  );
}

function isCancelled(o) {
  return ((o?.order_status || "").toUpperCase() === "CANCELLED");
}

function deliveryLine(o) {
  if (!o) return "—";
  if (isCancelled(o)) return "Cancelled — no delivery";
  return `Expected: ${o.expected_delivery_date || o.expected || o.estimated_delivery || "—"}`;
}

function OrderCard({ order, onClose }) {
  if (!order) return null;
  return (
    <div className="order-card">
      <div className="stackhead"><b>Order {order.order_number}</b><button className="xbtn" onClick={onClose} title="Hide">×</button></div>
      <div>Status: {order.order_status} · {order.delivery_status || order.delivery}</div>
      <div>{deliveryLine(order)}</div>
      <div>Total: ₹{order.total_amount}</div>
    </div>
  );
}

function senderLabel(s) {
  s = (s || "").toLowerCase();
  if (s === "ai") return "🤖 AI Support";
  if (s === "system") return "⚙️ System";
  if (s === "customer") return "You";
  return s;
}

const QUICK_ACTIONS = [
  { label: "Track Order", msg: "Where is my order?" },
  { label: "Return", msg: "I want to return my product." },
  { label: "Refund", msg: "When will I get my refund?" },
  { label: "Cancel Order", msg: "I want to cancel my order." },
  { label: "Service Request", msg: "I want to raise a service request." },
  { label: "Warranty", msg: "How can I claim warranty?" },
];

const TABS = [
  { id: "chat", label: "💬 Chat" },
  { id: "shop", label: "🛍️ Shop" },
  { id: "orders", label: "📦 Orders" },
  { id: "tickets", label: "🎫 Tickets" },
];

/* ---------------- Shop: search / details / similar / compare ---------------- */

function ShopPanel() {
  const [q, setQ] = useState("");
  const [brand, setBrand] = useState("");
  const [category, setCategory] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [minPrice, setMinPrice] = useState("");
  const [inStock, setInStock] = useState(false);
  const [results, setResults] = useState([]);
  const [brands, setBrands] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [detail, setDetail] = useState(null);
  const [similar, setSimilar] = useState([]);
  const [compareIds, setCompareIds] = useState([]);
  const [compareRows, setCompareRows] = useState([]);

  async function loadOptions() {
    try {
      const all = await api("/products");
      setBrands([...new Set(all.map((p) => p.brand).filter(Boolean))].sort());
      setCategories([...new Set(all.map((p) => p.category).filter(Boolean))].sort());
      setResults(all);
    } catch (e) { setErr(e.message); }
  }
  useEffect(() => { loadOptions(); }, []);

  async function search() {
    setLoading(true); setErr("");
    try {
      const ps = new URLSearchParams();
      if (q.trim()) ps.set("q", q.trim());
      if (brand) ps.set("brand", brand);
      if (category) ps.set("category", category);
      if (maxPrice) ps.set("max_price", maxPrice);
      if (minPrice) ps.set("min_price", minPrice);
      if (inStock) ps.set("in_stock_only", "1");
      setResults(await api(`/products?${ps.toString()}`));
    } catch (e) { setErr(e.message); }
    setLoading(false);
  }

  async function openDetail(p) {
    try {
      setErr("");
      setDetail(await api(`/products/${p.id}`));
      setSimilar(await api(`/products/${p.id}/similar?limit=4`));
    } catch (e) { setErr(e.message); }
  }

  function toggleCompare(id) {
    setCompareIds((xs) => xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id].slice(0, 4));
  }

  async function runCompare() {
    if (compareIds.length < 2) { setErr("Select at least 2 products to compare."); return; }
    try {
      setErr("");
      setCompareRows(await api(`/products/compare?ids=${compareIds.join(",")}`));
    } catch (e) { setErr(e.message); }
  }

  const cmpFields = [
    ["Name", (p) => p.product_name], ["Brand", (p) => p.brand], ["Category", (p) => p.category],
    ["Price", (p) => `₹${p.price}`], ["MRP", (p) => `₹${p.original_price}`],
    ["Rating", (p) => `⭐ ${p.rating}`], ["Stock", (p) => `${p.stock_quantity} (${p.in_stock ? "In stock" : "Out of stock"})`],
    ["Warranty", (p) => p.warranty_period || p.warranty], ["Return policy", (p) => p.return_policy],
    ["Description", (p) => p.description],
  ];

  return (
    <div className="card">
      <h3>Shop products</h3>
      <div className="formgrid">
        <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} placeholder="Search: samsung phone, laptop, headphone…" />
        <div className="formrow">
          <select value={brand} onChange={(e) => setBrand(e.target.value)}>
            <option value="">All brands</option>
            {brands.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All categories</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="formrow">
          <input type="number" value={minPrice} onChange={(e) => setMinPrice(e.target.value)} placeholder="Min price" />
          <input type="number" value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} placeholder="Max price" />
          <label className="check"><input type="checkbox" checked={inStock} onChange={(e) => setInStock(e.target.checked)} /> In stock only</label>
        </div>
        <div className="btnrow">
          <button onClick={search} disabled={loading}>{loading ? "Searching…" : "Search"}</button>
          <button className="secondary" onClick={() => { setQ(""); setBrand(""); setCategory(""); setMinPrice(""); setMaxPrice(""); setInStock(false); loadOptions(); }}>Reset</button>
        </div>
      </div>
      {err && <div className="bubble system"><b>⚙️ System</b><div>{err}</div></div>}
      <small>{results.length} product(s){compareIds.length >= 2 && ` · ${compareIds.length} selected for compare`}</small>
      <div className="products">
        {results.map((p) => (
          <div key={p.id} className="product-card">
            <b>{p.product_name}</b>
            <small>{p.brand} · {p.category}</small>
            <div className="price">₹{p.price} {p.original_price > p.price && <s>₹{p.original_price}</s>}</div>
            <small>⭐ {p.rating} · Stock: {p.stock_quantity}</small>
            <div className="btnrow">
              <button className="secondary" onClick={() => openDetail(p)}>Details</button>
              <button className={compareIds.includes(p.id) ? "" : "secondary"} onClick={() => toggleCompare(p.id)}>
                {compareIds.includes(p.id) ? "✓ Compared" : "Compare"}
              </button>
            </div>
          </div>
        ))}
      </div>
      {!results.length && !loading && <div className="empty">No products match the filters.</div>}
      {compareIds.length >= 2 && (
        <div className="btnrow"><button onClick={runCompare}>Compare {compareIds.length} products side-by-side</button>
        <button className="secondary" onClick={() => { setCompareIds([]); setCompareRows([]); }}>Clear compare</button></div>
      )}
      {!!compareRows.length && (
        <div className="comparewrap">
          <h4>Side-by-side comparison</h4>
          <table className="cmp">
            <thead><tr><th>Feature</th>{compareRows.map((p) => <th key={p.id}>{p.product_name}</th>)}</tr></thead>
            <tbody>
              {cmpFields.map(([label, fn]) => (
                <tr key={label}><td><b>{label}</b></td>{compareRows.map((p) => <td key={p.id}>{fn(p)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {detail && (
        <div className="order-card">
          <div className="stackhead"><b>{detail.product_name}</b><button className="xbtn" onClick={() => { setDetail(null); setSimilar([]); }}>×</button></div>
          <div>{detail.brand} · {detail.category} · ⭐ {detail.rating}</div>
          <div className="price">₹{detail.price} {detail.original_price > detail.price && <s>₹{detail.original_price}</s>} ({detail.discount}% off)</div>
          <div>Stock: {detail.stock_quantity} ({detail.in_stock ? "In stock" : "Out of stock"})</div>
          <div>Warranty: {detail.warranty_period || detail.warranty} · Returns: {detail.return_policy}</div>
          <p>{detail.description}</p>
          <small>{detail.specifications}</small>
          {!!similar.length && (
            <>
              <h4>Similar alternatives</h4>
              <div className="products">
                {similar.map((s) => (
                  <div key={s.id} className="product-card">
                    <b>{s.product_name}</b>
                    <small>{s.brand} · {s.category}</small>
                    <div className="price">₹{s.price}</div>
                    <small>⭐ {s.rating} · Stock: {s.stock_quantity}</small>
                    <div className="btnrow"><button className="secondary" onClick={() => openDetail(s)}>Details</button></div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------------- Orders: history + details ---------------- */

function OrdersPanel() {
  const [orders, setOrders] = useState([]);
  const [ref, setRef] = useState("");
  const [detail, setDetail] = useState(null);
  const [err, setErr] = useState("");

  async function load() {
    try { setErr(""); setOrders(await api("/orders")); }
    catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function openOrder(r) {
    try {
      setErr("");
      setDetail(await api(`/orders/${encodeURIComponent(r)}/details`));
    } catch (e) { setErr(e.message); }
  }

  return (
    <div className="card">
      <h3>Order history</h3>
      <div className="formrow">
        <input value={ref} onChange={(e) => setRef(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ref.trim() && openOrder(ref.trim())} placeholder="Order ID, e.g. RD100234" />
        <button onClick={() => ref.trim() && openOrder(ref.trim())}>View</button>
      </div>
      {err && <div className="bubble system"><b>⚙️ System</b><div>{err}</div></div>}
      {!orders.length && <div className="empty">No past purchases yet.</div>}
      {orders.map((o) => (
        <div key={o.order_number || o.id} className="ticket">
          <b>{o.order_number}</b>
          <small>{o.order_status} · {o.delivery_status || o.delivery} · ₹{o.total_amount} · {isCancelled(o) ? "no delivery" : (o.expected_delivery_date || o.expected)}</small>
          <div className="btnrow"><button className="secondary" onClick={() => openOrder(o.order_number)}>Details</button></div>
        </div>
      ))}
      {detail && (
        <div className="order-card">
          <div className="stackhead"><b>Order {detail.order_number}</b><button className="xbtn" onClick={() => setDetail(null)}>×</button></div>
          <div>Status: {detail.order_status} · Delivery: {detail.delivery_status || detail.delivery}</div>
          <div>{deliveryLine(detail)}</div>
          <div>Total: ₹{detail.total_amount} · Tracking: {detail.tracking_number || "—"}</div>
          {!!detail.items?.length && (
            <div><b>Items</b>{detail.items.map((i, n) => <div key={n}>{i.product_name} × {i.quantity} — ₹{i.price}</div>)}</div>
          )}
          {detail.payment && <div>Payment: {detail.payment.method} · {detail.payment.status} · ₹{detail.payment.amount}</div>}
        </div>
      )}
    </div>
  );
}

/* ---------------- Tickets: history + detail + create + update ---------------- */

function TicketsPanel() {
  const [tickets, setTickets] = useState([]);
  const [ref, setRef] = useState("");
  const [detail, setDetail] = useState(null);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("MEDIUM");
  const [edit, setEdit] = useState({ subject: "", description: "", priority: "MEDIUM", status: "OPEN" });

  async function load() {
    try { setErr(""); setTickets(await api("/tickets")); }
    catch (e) { setErr(e.message); }
  }
  useEffect(() => { load(); }, []);

  async function openTicket(r) {
    try {
      setErr(""); setOk("");
      const t = await api(`/tickets/${encodeURIComponent(r)}`);
      setDetail(t);
      setEdit({ subject: t.subject || "", description: t.description || "", priority: t.priority || "MEDIUM", status: t.status || "OPEN" });
    } catch (e) { setErr(e.message); }
  }

  async function create() {
    try {
      setErr(""); setOk("");
      const t = await api("/tickets", { method: "POST", body: JSON.stringify({ subject, description, priority }) });
      setOk(`Ticket ${t.ticket_number} created.`);
      setSubject(""); setDescription(""); setPriority("MEDIUM");
      await load();
    } catch (e) { setErr(e.message); }
  }

  async function update() {
    if (!detail) return;
    try {
      setErr(""); setOk("");
      const t = await api(`/tickets/${encodeURIComponent(detail.ticket_number)}`, { method: "PATCH", body: JSON.stringify(edit) });
      setDetail(t); setOk(`Ticket ${t.ticket_number} updated.`);
      await load();
    } catch (e) { setErr(e.message); }
  }

  return (
    <div className="card">
      <h3>Support tickets</h3>
      <div className="formrow">
        <input value={ref} onChange={(e) => setRef(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ref.trim() && openTicket(ref.trim())} placeholder="Ticket ID, e.g. TKT10001" />
        <button onClick={() => ref.trim() && openTicket(ref.trim())}>View</button>
      </div>
      {err && <div className="bubble system"><b>⚙️ System</b><div>{err}</div></div>}
      {ok && <div className="bubble ai"><b>🤖 AI Support</b><div>{ok}</div></div>}
      <h4>Ticket history</h4>
      {!tickets.length && <div className="empty">No tickets yet — create one below.</div>}
      {tickets.map((t) => (
        <div key={t.ticket_number || t.id} className="ticket">
          <b>{t.ticket_number}</b>
          <small>{t.subject} · {t.status} · {t.priority}</small>
          <div className="btnrow"><button className="secondary" onClick={() => openTicket(t.ticket_number)}>Details</button></div>
        </div>
      ))}
      {detail && (
        <div className="order-card">
          <div className="stackhead"><b>{detail.ticket_number}</b><button className="xbtn" onClick={() => setDetail(null)}>×</button></div>
          <div>{detail.subject} · {detail.status} · {detail.priority}</div>
          <p>{detail.description}</p>
          <h4>Update this ticket</h4>
          <div className="formgrid">
            <input value={edit.subject} onChange={(e) => setEdit({ ...edit, subject: e.target.value })} placeholder="Subject" />
            <textarea value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} placeholder="Description" rows={3} />
            <div className="formrow">
              <select value={edit.priority} onChange={(e) => setEdit({ ...edit, priority: e.target.value })}>
                {["LOW", "MEDIUM", "HIGH", "URGENT"].map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
              <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
                {["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <button onClick={update}>Save</button>
            </div>
          </div>
        </div>
      )}
      <h4>Create a support ticket</h4>
      <div className="formgrid">
        <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject, e.g. Late delivery for RD100234" />
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Describe the issue…" rows={3} />
        <div className="formrow">
          <select value={priority} onChange={(e) => setPriority(e.target.value)}>
            {["LOW", "MEDIUM", "HIGH", "URGENT"].map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <button onClick={create}>Create ticket</button>
        </div>
      </div>
    </div>
  );
}

/* ---------------- Customer with tabs ---------------- */

function Customer() {
  const [tab, setTab] = useState("chat");
  const [msg, setMsg] = useState("");
  const [chat, setChat] = useState([{ sender: "ai", content: "Hi! Welcome to our customer support. How can I help you?" }]);
  const [cid, setCid] = useState(null);
  const [status, setStatus] = useState("AI_ACTIVE");
  const [lastProducts, setLastProducts] = useState([]);
  const [lastOrder, setLastOrder] = useState(null);
  const [lastService, setLastService] = useState(null);
  const [models, setModels] = useState([]);
  const [model, setModel] = useState(() => localStorage.getItem("ai_model") || "auto");
  const [tickets, setTickets] = useState([]);
  const [services, setServices] = useState([]);
  const [showTickets, setShowTickets] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    api("/models").then(setModels).catch(() => setModels([]));
    api("/tickets").then(setTickets).catch(() => {});
    api("/service-requests").then(setServices).catch(() => {});
  }, []);

  function pickModel(m) {
    setModel(m);
    localStorage.setItem("ai_model", m);
  }

  async function refresh(silent = true, id = cid) {
    if (!id) return;
    try {
      const d = await api(`/conversations/${id}`);
      setStatus(d.status);
      setChat(d.messages.map((m) => ({ sender: m.sender, content: m.content, type: m.message_type, model: m.ai_model })));
    } catch (e) { if (!silent) alert(e.message); }
  }

  // polling: updates without full page refresh (Socket.IO-ready backend emits too)
  useEffect(() => {
    if (!cid) return;
    const t = setInterval(() => refresh(true), 3000);
    return () => clearInterval(t);
  }, [cid]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [chat]);

  async function sendText(text) {
    if (!text.trim()) return;
    const isNew = !cid;
    setMsg("");
    setChat((x) => [...x, { sender: "customer", content: text }]);
    try {
      const d = isNew
        ? await api("/chat", { method: "POST", body: JSON.stringify({ message: text, model }) })
        : await api(`/conversations/${cid}/message`, { method: "POST", body: JSON.stringify({ message: text, model }) });
      const newCid = d.conversation_id || cid;
      setCid(newCid);
      setStatus(d.status);
      if (d.products && d.products.length) setLastProducts(d.products);
      if (d.order) setLastOrder(d.order);
      if (d.service) { setLastService(d.service); api("/service-requests").then(setServices).catch(() => {}); }
      if (isNew) {
        // refresh() can't load a brand-new chat yet, so append the reply directly
        if (d.reply) setChat((x) => [...x, { sender: "ai", content: d.reply, model: d.model_used }]);
      } else {
        // history from the server already contains the new AI reply — don't append it again
        await refresh(true, newCid);
      }
      api("/tickets").then(setTickets).catch(() => {});
    } catch (e) {
      setChat((x) => [...x, { sender: "system", content: e.message }]);
    }
  }
  async function send() { await sendText(msg); }

  function newChat() {
    setCid(null);
    setStatus("AI_ACTIVE");
    setChat([{ sender: "ai", content: "Hi! Welcome to our customer support. How can I help you?" }]);
    setLastProducts([]);
    setLastOrder(null);
    setLastService(null);
  }

  return (
    <Shell title="Customer Support">
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={"tabbtn" + (tab === t.id ? " active" : "")} onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>
      {tab === "chat" && (
      <div className="grid">
        <section className="card chat">
          <div className="chathead">
            <b>Support conversation</b>
            <span className="headerright">
              <select className="modelpick" value={model} onChange={(e) => pickModel(e.target.value)} title="AI model (switch anytime, history is kept)">
                <option value="auto">Auto (recommended)</option>
                {models.filter((m) => m.id !== "auto").map((m) => (
                  <option key={m.id} value={m.id} disabled={!m.available}>
                    {m.label}{m.available ? "" : " (unavailable)"}
                  </option>
                ))}
              </select>
              <span className={"badge " + status}>{status.replaceAll("_", " ")}</span>
            </span>
          </div>
          <div className="quickbar">
            {QUICK_ACTIONS.map((q) => (
              <button key={q.label} className="chip" onClick={() => sendText(q.msg)}>{q.label}</button>
            ))}
          </div>
          <div className="messages">
            {chat.map((m, i) => (
              <div key={i} className={"bubble " + m.sender}>
                <b>{senderLabel(m.sender)}{m.model ? ` · ${m.model}` : ""}</b>
                <div>{m.content}</div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
          <ProductCards products={lastProducts} onClose={() => setLastProducts([])} />
          <OrderCard order={lastOrder} onClose={() => setLastOrder(null)} />
          {lastService && (
            <div className="order-card">
              <div className="stackhead"><b>Service {lastService.request_number}</b><button className="xbtn" onClick={() => setLastService(null)} title="Hide">×</button></div>
              <div>{lastService.issue_type} · {lastService.status}</div>
              <div>Pickup: {lastService.pickup_status} · Delivery: {lastService.delivery_status}</div>
            </div>
          )}
          <div className="composer">
            <input value={msg} onChange={(e) => setMsg(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder='Try: "Where is my order?", "I want to return my product", "Status of my repair?"' />
            <button onClick={send}>Send</button>
          </div>
          <div className="composer" style={{ marginTop: 8 }}>
            <button className="secondary" onClick={newChat}>Start a new chat</button>
          </div>
        </section>
        <aside className="card side">
          <h3>My support</h3>
          <button className="secondary" onClick={() => { setShowTickets((s) => !s); api("/tickets").then(setTickets).catch(() => {}); api("/service-requests").then(setServices).catch(() => {}); }}>
            {showTickets ? "Hide requests" : "My requests & tickets"}
          </button>
          {showTickets && (
            <div className="ticketlist">
              {!!services.length && <h4>Service requests</h4>}
              {services.map((s) => (
                <div key={s.request_number || s.id} className="ticket">
                  <b>{s.request_number}</b>
                  <small>{s.issue_type} · {s.status} · pickup {s.pickup_status}</small>
                </div>
              ))}
              {!!tickets.length && <h4>Support tickets</h4>}
              {tickets.map((t) => (
                <div key={t.ticket_number || t.id} className="ticket">
                  <b>{t.ticket_number || t.ticket_id}</b>
                  <small>{t.subject} · {t.status}</small>
                </div>
              ))}
              {!services.length && !tickets.length && <div className="empty">No requests yet.</div>}
            </div>
          )}
          <h3>Quick help</h3>
          <button className="secondary" onClick={() => sendText("Where is my previous order?")}>Track my order</button>
          <button className="secondary" onClick={() => sendText("When will I get my refund?")}>Refund status</button>
          <button className="secondary" onClick={() => sendText("What is the status of my repair?")}>Repair status</button>
        </aside>
      </div>
      )}
      {tab === "shop" && <ShopPanel />}
      {tab === "orders" && <OrdersPanel />}
      {tab === "tickets" && <TicketsPanel />}
    </Shell>
  );
}

function Admin() {
  const [d, setD] = useState(null);
  useEffect(() => { api("/admin/analytics").then(setD); }, []);
  return (
    <Shell title="Admin Analytics">
      {d && (
        <>
          <div className="stats">
            <Stat n={d.total_conversations} t="Conversations" />
            <Stat n={d.ai_resolution_rate + "%"} t="AI resolution" />
            <Stat n={d.open_tickets} t="Open tickets" />
            <Stat n={d.customer_satisfaction} t="CSAT" />
          </div>
          <div className="card"><h2>Operational overview</h2><p>Metrics are calculated from application data only.</p></div>
        </>
      )}
    </Shell>
  );
}

function Stat({ n, t }) { return <div className="stat"><b>{n}</b><span>{t}</span></div>; }

function Shell({ title, children }) {
  return (
    <div>
      <header>
        <div className="brand">◈ SupportFlow</div>
        <h2>{title}</h2>
        <button className="logout" onClick={() => { localStorage.clear(); location.reload(); }}>Logout</button>
      </header>
      <main>{children}</main>
    </div>
  );
}

function App() {
  const [user, setUser] = useState(() => {
    try { return JSON.parse(localStorage.getItem("user") || "null"); }
    catch { return null; }
  });
  if (!user) return <Login setUser={setUser} />;
  // Old agent logins are no longer valid in pure-AI mode — force fresh login.
  if (user.role !== "admin" && user.role !== "customer") {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    return <Login setUser={setUser} />;
  }
  return user.role === "admin" ? <Admin /> : <Customer />;
}

createRoot(document.getElementById("root")).render(<App />);
