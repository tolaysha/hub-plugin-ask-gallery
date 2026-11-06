// "Questions only": a session mode where the whole screen holds only its open questions, a gallery of one at a time, and
// next to each card what led to it (chain.js): the session's text nearest to it in the turn it was asked in, and when
// that turn was started by the owner's answer, the earlier question and that answer first. A card is the page's own question
// card (cards.js askCard): the answer goes the same /api/answer way with retries and a receipt, "close without an answer"
// the same /api/question/dismiss; the plugin sends nothing of its own to the core and only reads the feed (/api/history).
// It keeps only the open session's name for the tab's life (sessionStorage): the page reloads after a hub update, the mode
// stays. In this browser it keeps the widths of the context and the card the owner dragged them to (localStorage). The mode
// takes one history entry, so Back (the phone's back gesture) leaves it. With no open questions left it goes back to the
// hub at once.
import { askCard } from "/static/js/cards.js";
import { avatarNode } from "/static/js/dom.js";
import { S, sessionLabel } from "/static/js/state.js";
import { V } from "/static/js/recorder.js";
import { dictationIn } from "/static/js/dictate.js";
import { item, keyOf } from "/static/js/feed.js";
import { context } from "./chain.js";

const WORDS = {
  ru: { open: "Только вопросы", openN: (n) => `Только вопросы: открыто ${n}`, exit: "Выйти из режима вопросов (Esc)",
    of: (i, n) => `${i} из ${n}`, prev: "Предыдущий вопрос (←)", next: "Следующий вопрос (→)", nav: "Вопросы",
    label: (name) => `Вопросы сессии ${name}`, drop: "Убрать",
    context: "Контекст вопроса", loading: "Загружаю контекст…", failed: "Не удалось загрузить контекст", retry: "Повторить",
    more: "ещё", less: "свернуть",
    split: "Ширина контекста и вопроса", edge: "Ширина вопроса",
    gripHint: "Тяните или ←/→ — ширина; двойной клик — по умолчанию" },
  en: { open: "Questions only", openN: (n) => `Questions only: ${n} open`, exit: "Leave questions mode (Esc)",
    of: (i, n) => `${i} of ${n}`, prev: "Previous question (←)", next: "Next question (→)", nav: "Questions",
    label: (name) => `Questions of ${name}`, drop: "Remove",
    context: "Context of the question", loading: "Loading the context…", failed: "Could not load the context", retry: "Retry",
    more: "more", less: "less",
    split: "Width of the context and the question", edge: "Width of the question",
    gripHint: "Drag or ←/→ — the width; double-click — back to default" },
};
const KEEP = "ask-gallery.open";   // sessionStorage: the session whose questions are open
const MARK = "askGallery";         // the mode's own history entry (history.state[MARK] = the session)
const TICK = 250;                   // how often the open mode looks at the snapshot and at the shown card
const SHIFT = 24;                   // percent of the card width it travels while sliding
const PAGE = 200, PAGES = 10;       // the context: feed rows asked from /api/history at a time, and how far back at most (pages of a session)
const POLL = 3000;                  // the context's rows: newer ones this often (the session's text after the card)
const SIZE = "ask-gallery.widths";  // localStorage: { ctx, card } — the widths the owner dragged to, px
const WIDE = { ctx: 380, card: 680 };       // the default widths
const LEAST = { ctx: 240, card: 400 };      // narrower than this, neither is readable

let hub, W;
const cards = new Map();   // key -> { node: askCard form, slide, ctx: context box, asker, rid, frozen? } — typed text survives snapshots
const feeds = new Map();   // session -> { rows: Map key -> row, more, loading, failed, pages, newest, polled } — the context's rows
let m = null;              // the open mode: { name, items: [key], cur, slide, layer parts, timer, opener, room, fit }
let want = null;           // the widths asked for (dragged, or the default); shown as they fit the screen (fitted)
let held = null;           // a handle being dragged: how to let it go (the card under it may leave meanwhile)

const quiet = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const ms = (name, fallback) => parseFloat(css(name)) || fallback;

function plugIcon(file) {
  const i = hub.el("span", "icon ext-icon ag-icon");
  i.style.setProperty("--src", `url("${hub.url(`web/icons/${file}.svg`)}")`);
  i.setAttribute("aria-hidden", "true");
  return i;
}

function button(cls, label, ico) {
  const b = hub.el("button", `btn quiet ${cls}`);
  b.type = "button";
  b.title = label;
  b.setAttribute("aria-label", label);
  b.append(ico);
  return b;
}

// the session's open questions, oldest first: its own (pending) and, for the hub, the ones it shows in its chat
function asks(s) {
  const own = (s.pending || []).filter((r) => r.tool === "AskUserQuestion")
    .map((req) => ({ key: `${s.name}:req:${req.request_id}`, req, asker: s.name }));
  const shown = (s.shown || []).map((req) => ({ key: `${s.name}:shown:${req.session}:${req.request_id}`, req, asker: req.session }));
  return [...own, ...shown];
}

// the card has left on our side: the core took the answer (got) or the question was closed without one (hidden)
const left = (key) => { const c = cards.get(key)?.node; return !!c && (!!c.dataset.got || c.hidden || !!c.dataset.agClosed); };

function build() {
  const layer = hub.el("div", "ag-layer");
  layer.setAttribute("role", "dialog");
  layer.setAttribute("aria-modal", "true");
  layer.tabIndex = -1;   // the focus lands here after a card leaves: ←/→ keep working
  const top = hub.el("header", "ag-top"), who = hub.el("h2", "ag-who");
  who.id = "ag-who";
  layer.setAttribute("aria-labelledby", who.id);
  const x = button("ag-x", W.exit, hub.icon("close"));
  x.addEventListener("click", () => close());
  const say = hub.el("p", "ag-say");   // the page's banner (no connection, a late refusal) sits under the layer
  say.setAttribute("role", "status");
  say.hidden = true;
  top.append(who, say, x);
  const stage = hub.el("div", "ag-stage");
  const nav = hub.el("nav", "ag-nav");
  nav.setAttribute("aria-label", W.nav);
  const prev = button("ag-prev", W.prev, plugIcon("back")), next = button("ag-next", W.next, plugIcon("forward"));
  const count = hub.el("span", "ag-count");
  count.setAttribute("aria-live", "polite");
  prev.addEventListener("click", () => step(-1));
  next.addEventListener("click", () => step(1));
  nav.append(prev, count, next);
  layer.append(top, stage, nav);
  swipe(stage);
  return { layer, who, say, stage, prev, next, count, sig: null };
}

function open(name, opener) {
  if (m) return;
  if (history.state?.[MARK] !== name) history.pushState({ ...history.state, [MARK]: name }, "");   // a reload is already on it
  m = { name, items: [], cur: null, slide: null, opener: opener || null, ...build() };
  try { sessionStorage.setItem(KEEP, name); } catch { /* no storage */ }
  want = stored();
  document.body.append(m.layer);
  m.gap = ms("--space-6", 24);       // between the context and the card (ask-gallery.css)
  m.width = roomOf(m.stage);
  // the window or the stage's scrollbar: the widths fit the room again (measured here, not on every tick)
  m.room = new ResizeObserver(([e]) => { m.width = e.contentRect.width; layout(); });
  m.room.observe(m.stage);
  const app = document.getElementById("app");
  if (app) app.inert = true;   // Tab and screen readers stay inside the mode
  sync(true);
  if (!m) return;   // nothing to answer (a reload after the last question left): the mode has closed already
  m.timer = setInterval(() => sync(false), TICK);
  m.layer.focus();
}

// fromHistory: Back already took the mode's entry; otherwise the entry is given back here
function close(fromHistory = false) {
  if (!m) return;
  if (!fromHistory && history.state?.[MARK]) history.back();
  held?.();
  clearInterval(m.timer);
  m.room?.disconnect();
  m.layer.remove();
  m.slide?.remove();
  const app = document.getElementById("app");
  if (app) app.inert = false;
  try { sessionStorage.removeItem(KEEP); } catch { /* no storage */ }
  const back = m.items.length ? m.opener : null;   // none left: the header button is going away, the page has not hidden it yet
  m = null;
  prune();
  feeds.clear();   // read anew next time: the page's feed moves on meanwhile, the rows kept here would have a gap
  if (back?.isConnected && back.getClientRects().length) back.focus();
  // no questions left: the session's field, except on a touch screen (its keyboard would come up by itself)
  else if (!matchMedia("(pointer: coarse)").matches) document.getElementById("msg")?.focus();
}

// the snapshot and the shown card → the list: answered and closed ones leave, new ones are added at the end
function sync(first) {
  const snap = hub.snapshot();
  if (!snap || !m) return;
  const s = (snap.sessions || []).find((x) => x.name === m.name);
  const all = s ? asks(s) : [], open = new Set(all.map((w) => w.key));
  // a card stays cached while its question is in the snapshot: typed text survives, and an answered one is not
  // made again while the snapshot still lags behind the answer
  for (const [k, c] of [...cards]) {
    if (!k.startsWith(m.name + ":")) continue;
    if (!c.node.dataset.got && ours(c.node)) {
      c.node.dataset.got = "1";   // the core recorded our own answer: it leaves, never frozen
    }
    if (open.has(k)) { if (c.frozen) cards.delete(k); continue; }   // the same question open again: a live card
    // closed elsewhere (another device, Telegram) while the owner was typing here: the card stays, frozen, with the
    // text — as the page's feed does (dock.js)
    if (!c.frozen && !left(k) && !c.node.dataset.closing && (typed(c.node) || dictationIn(c.node))) freeze(c);
    else if (!c.frozen || left(k)) cards.delete(k);
  }
  prune();
  for (const w of all) {
    if (cards.has(w.key)) continue;
    const node = askCard(s, w.req), slide = hub.el("div", "ag-slide"), ctx = contextBox();
    slide.append(ctx.box, grip("split"), node, grip("edge"));   // Tab goes as the eye does: the context, the divider, the card
    cards.set(w.key, { node, slide, ctx, asker: w.asker, rid: w.req.request_id, at: w.req.since ?? null, sig: null });
  }
  const frozen = [...cards].filter(([k, c]) => c.frozen && k.startsWith(m.name + ":") && !left(k)).map(([k]) => k);
  // a frozen card's question is older than the open ones: it goes first when the list is built anew
  const live = [...frozen, ...all.map((w) => w.key).filter((k) => !left(k))], keep = new Set(live);
  const label = s ? sessionLabel(s) : m.name, sig = `${s?.icon || ""} ${label}`;
  if (m.sig !== sig) {
    m.sig = sig;
    m.who.replaceChildren(...(s?.icon ? [avatarNode(s.icon, "avatar ag-av"), document.createTextNode(" ")] : []), label);
    m.who.title = label;   // a long name is cut with an ellipsis
    m.layer.setAttribute("aria-label", W.label(label));
  }
  const b = document.getElementById("banner"), say = b?.classList.contains("on") ? b.textContent : "";
  if (m.say.textContent !== say) { m.say.textContent = say; m.say.hidden = !say; }
  const before = m.items;
  m.items = [...before.filter((k) => keep.has(k)), ...live.filter((k) => !before.includes(k))];
  // nothing left to answer: back to the hub at once, as by Esc — without waiting for the session to take the answer.
  // A frozen card counts as a question: the owner's typed or dictated text holds the mode
  if (!m.items.length) return void close();
  if (first) show(m.items[0], 1, false, true);
  else if (!keep.has(m.cur)) {
    // the shown question is answered or closed: it leaves, the one after it comes (the one before it, if it was the last)
    const was = before.indexOf(m.cur);
    const after = before.slice(was + 1).find((k) => keep.has(k));
    const prior = before.slice(0, was).reverse().find((k) => keep.has(k));
    show(after || prior || m.items[0], after ? 1 : -1, true);   // or one that came on the same tick
  } else if (cards.get(m.cur)?.slide !== m.slide) {
    const k = m.cur;   // the same question was asked again: its live card takes the frozen one's place
    m.cur = null;
    show(k, 1, false, true);
  }
  for (const k of m.items) fill(cards.get(k));
  paint();
  layout();
}

// the same tests as the page's feed (dock.js typed, ours)
const typed = (f) => [...f.querySelectorAll("textarea, input[type=text]")].some((x) => x.value.trim())
  || [...f.querySelectorAll(".dictate-note[data-said]")].some((x) => x.dataset.said);
function ours(f) {
  if (!f.dataset.cid) return false;
  const to = (hub.snapshot()?.sessions || []).find((x) => x.name === f.dataset.to);
  return !!to?.answered?.some((r) => r.request_id === f.dataset.rid && r.client_id === f.dataset.cid);
}

// cached cards of questions that are gone, of any session (the cache outlives the mode), except frozen ones
function prune() {
  const open = new Set((hub.snapshot()?.sessions || []).flatMap((s) => asks(s).map((w) => w.key)));
  for (const [k, c] of [...cards]) if (!open.has(k) && !c.frozen && c.slide !== m?.slide) cards.delete(k);
}

// as the page's own feed does with such a card (dock.js freeze): nothing can be sent from it, the text stays to copy
function freeze(c) {
  c.frozen = true;
  const f = c.node;
  f.dataset.frozen = "1";   // cards.js sends nothing from a frozen card
  f.classList.add("frozen");
  f.classList.remove("sent");   // collapsed while our answer is in flight: the typed text is visible again
  f.querySelector(".sent-line")?.remove();
  const dictation = (x) => x.matches(".dictate") || !!x.closest(".dictate-note");   // a running recording finishes
  for (const x of f.querySelectorAll("input, textarea, button")) {
    if (x.matches("textarea, input[type=text]")) x.readOnly = true;
    else if (!dictation(x)) x.disabled = true;
  }
  for (const x of f.querySelectorAll(".dictate")) x.hubPaint?.();
  // the header is what became of the question, as on the page's card: answered elsewhere, or closed
  const h = f.querySelector(".card-head h3");
  const answered = rowsOf(c.asker).some((it) => it.kind === "answer" && it.request_id === c.rid);
  if (h) { h.classList.add("frozen-note"); h.textContent = hub.t(answered ? "web.cards.frozen_answered" : "web.cards.frozen_closed"); }
  const bar = hub.el("div", "frozen-bar"), drop = hub.el("button", "btn small", W.drop);
  drop.type = "button";
  drop.addEventListener("click", () => { f.dataset.agClosed = "1"; sync(false); });
  bar.append(drop);
  bar.setAttribute("role", "status");
  f.append(bar);
}

function paint() {
  const n = m.items.length, at = Math.max(m.items.indexOf(m.cur), 0), of = W.of(at + 1, n);
  if (m.count.textContent !== of) m.count.textContent = of;   // a live region: rewritten only when it changes
  m.prev.disabled = at <= 0;
  m.next.disabled = at >= n - 1;
}

// keys: a plain swap (motion on a keyboard shortcut only delays the next press); buttons and a swipe slide
function step(d, byKey = false) {
  if (!m) return;
  const at = m.items.indexOf(m.cur) + d;
  if (at < 0 || at >= m.items.length) return;
  show(m.items[at], d, false, byKey);
  paint();
}

// one card on screen: the old one slides out, the new one slides in from the side of the move; an answered card goes
// up and fades. With reduced motion nothing moves: a move is a plain swap, an answer is a fade
function show(key, dir, answered, still = false) {
  // the shown slide is held by the mode, not looked up in the cache: the snapshot may drop the answered question
  // (and its cache entry) before the answer's receipt comes back
  const from = m.slide, to = key ? cards.get(key)?.slide || null : null;
  m.cur = key;
  m.slide = to;
  layout();   // its handles' values at once, not on the next tick
  // a quick second move does not stack up. Only the slides' own moves, never an endless one: inside a card there may run
  // one (a theme's blinking caret, the dictation spinner), and finishing it throws — the move would stop halfway
  for (const s of m.stage.children) for (const a of s.getAnimations()) if (a.effect?.getComputedTiming().endTime !== Infinity) a.finish();
  if (from === to) return;
  held?.();
  // the focus was on the leaving card, or already dropped to the page (cards.js blurs the card it sends from)
  const f = document.activeElement, lost = (!!from && from.contains(f)) || f === m.layer || !m.layer.contains(f);
  if (to) {
    if (to.parentNode !== m.stage) m.stage.append(to);
    to.inert = false;
  }
  paint();
  if (lost) m.layer.focus({ preventScroll: true });   // ←/→ keep working
  const calm = quiet(), fade = calm && answered;
  still ||= calm && !answered;
  const ease = css("--ease-out") || "ease-out", out = ms("--dur-fast", 160), inn = ms("--dur", 240);
  if (to && !still) to.animate(fade ? [{ opacity: 0 }, { opacity: 1 }]
    : [{ opacity: 0, transform: `translateX(${dir * SHIFT}%)` }, { opacity: 1, transform: "none" }],
    { duration: fade ? out : inn, easing: ease, delay: answered && from ? out / 2 : 0, fill: "backwards" });
  if (!from) return;
  from.inert = true;
  const card = from.querySelector(":scope > .card");
  if (card.hidden) { card.dataset.agClosed = "1"; card.hidden = false; }   // closed without an answer: it leaves visibly too
  if (still) return void from.remove();
  const gone = fade ? [{ opacity: 1 }, { opacity: 0 }] : answered
    ? [{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateY(-12%) scale(0.96)" }]
    : [{ opacity: 1, transform: "none" }, { opacity: 0, transform: `translateX(${-dir * SHIFT}%)` }];
  const a = from.animate(gone, { duration: answered && !fade ? inn : out, easing: ease });
  a.onfinish = a.oncancel = () => { if (m?.slide !== from) from.remove(); };
}

// ---- the context of a question ----

// the rows known for a session: what the plugin loaded from /api/history and the page's own feed of it (live)
function rowsOf(name) {
  const f = feeds.get(name), live = (S.cur?.name === name && hub.snapshot()?.timelines?.[name]) || [];
  if (!f) return live;
  const all = new Map(f.rows);
  for (const it of live) all.set(keyOf(it), it);
  return [...all.values()];
}
const feedOf = (name) => feeds.get(name) || feeds.set(name, { rows: new Map(), more: true, loading: false, failed: false,
  building: false, pages: 0, newest: 0, polled: 0, rev: 0 }).get(name);

// the feed's past for the context (as the page's feed loads it on scrolling up): the latest rows first, then earlier ones
// newer: the rows after the newest one known (one page; the next poll goes on from there) — the rows stay without a gap
async function load(name, newer = false) {
  const f = feedOf(name);
  if (f.loading || f.building) return;
  f.loading = true;
  let r = null;
  for (let n = 0; n < PAGES; n++) {
    const seqs = [...f.rows.values()].map((it) => it.seq);
    const q = newer ? `after=${f.newest}` : `before=${f.pages && seqs.length ? Math.min(...seqs) : 1e12}`;
    r = null;
    try {
      const res = await fetch(`/api/history?session=${encodeURIComponent(name)}&n=${PAGE}&${q}`);
      if (res.ok) r = await res.json();
    } catch { /* network: the box says so, with "Retry" */ }
    if (feeds.get(name) !== f) return;   // the mode was left meanwhile: these rows belong to no one
    if (!r || !Array.isArray(r.items)) break;
    for (const it of r.items) f.rows.set(keyOf(it), it);
    if (r.items.length) f.newest = Math.max(f.newest, ...r.items.map((it) => it.seq));
    f.rev += 1;
    if (!newer || !r.more || !r.items.length) break;   // (the page server's "after" pages have no more: one page)
  }
  f.loading = false;
  if (newer) f.polled = Date.now();
  if (!r || !Array.isArray(r.items)) { if (!newer) f.failed = true; return void (m && sync(false)); }
  f.failed = false;
  if (!newer) {
    if (r.building) {   // the journal archive is still being parsed: once more in a while, not on every tick
      f.building = true;
      setTimeout(() => { if (feeds.get(name) === f) { f.building = false; load(name); } }, 3000);
    } else { f.pages += 1; f.more = !!r.more; }
  }
  if (m) sync(false);
}

function contextBox() {
  const box = hub.el("aside", "ag-ctx"), body = hub.el("div", "ag-ctx-body"), more = hub.el("button", "linkbtn ag-ctx-more", W.more);
  box.setAttribute("aria-label", W.context);
  box.hidden = true;
  more.type = "button";
  more.hidden = true;
  more.setAttribute("aria-expanded", "false");
  box.tabIndex = -1;   // "Retry" goes away when pressed: the focus lands on the box
  more.addEventListener("click", () => {
    const open = box.classList.toggle("open");
    more.textContent = open ? W.less : W.more;
    more.setAttribute("aria-expanded", String(open));
  });
  box.append(body, more);
  // "more" only where the box is folded (a narrow screen) and the text does not fit
  new ResizeObserver(() => fits(box, body, more)).observe(body);
  return { box, body, more };
}
function fits(box, body, more) {
  more.hidden = !box.classList.contains("open") && body.scrollHeight <= body.clientHeight + 1;
}

// a feed row as the feed draws it, without what acts on the session's own feed (reply, reactions, the jump by quote)
function bare(it) {
  const r = item(it);
  if (!r?.querySelectorAll) return r;
  r.querySelectorAll(".reply-btn, .react-add, .reactions").forEach((x) => x.remove());
  for (const q of r.querySelectorAll(".quote-jump, .in-reply")) {
    const plain = q.cloneNode(true);
    plain.removeAttribute("role");
    plain.removeAttribute("tabindex");
    q.replaceWith(plain);
  }
  for (const x of [r, ...r.querySelectorAll(".row")]) delete x.__quote;
  return r;
}

// the context of a card: asked for its session's feed, redrawn when what it shows changed (the session's text after the
// card comes later than the card itself)
function fill(c) {
  if (!c || c.frozen) return;
  const f = feedOf(c.asker), snap = hub.snapshot(), free = !f.loading && !f.building && !(f.failed && !f.pages);
  if (!f.pages && free) load(c.asker);
  // the context is worked out again only when its rows changed (the page's feed of the open session, the rows loaded here)
  const live = S.cur?.name === c.asker ? snap?.timelines?.[c.asker] : null;
  const key = `${f.rev}|${f.pages}|${f.more}|${live?.length ?? -1}|${live?.at(-1)?.rev ?? ""}`;
  if (f.pages && key !== c.key) { c.key = key; c.got = context(rowsOf(c.asker), c.rid, snap?.messages || {}, f.more); }
  const got = f.pages ? c.got : null;
  const older = f.pages && f.more && free && f.pages < PAGES && (c.pages || 0) < PAGES;
  // its row is older than the loaded ones, or its turn, or the answered question, begins before them: earlier pages
  if (older && ((!got && c.at != null && c.at < Math.min(...[...f.rows.values()].map((it) => it.ts))) || (got && !got.whole))) {
    c.pages = (c.pages || 0) + 1;
    load(c.asker);
  }
  else if (f.pages && free && Date.now() - f.polled > POLL) load(c.asker, true);   // newer rows: its own row, its text after it
  const rows = got ? [got.ask, got.answer, ...got.said].filter(Boolean) : [];
  const state = !f.pages ? (f.failed ? "failed" : "loading") : "ok";   // an earlier page failed: what is there stays
  const sig = `${state}|${rows.map(keyOf).join(",")}`;
  if (sig === c.sig) return;
  c.sig = sig;
  const { box, body, more } = c.ctx;
  if (state === "loading") body.replaceChildren(hub.el("p", "hint ag-ctx-note", W.loading));
  else if (state === "failed") {
    const again = hub.el("button", "btn small", W.retry), p = hub.el("p", "hint ag-ctx-note", W.failed + " ");
    again.type = "button";
    again.addEventListener("click", () => { f.failed = false; box.focus(); load(c.asker); sync(false); });
    p.append(again);
    body.replaceChildren(p);
  } else body.replaceChildren(...rows.map(bare).filter(Boolean));
  box.hidden = state === "ok" && !rows.length;   // nothing came before it: the card alone, in the middle
  c.slide.classList.toggle("with-ctx", !box.hidden);
  fits(box, body, more);
}

// ---- the widths of the context and the card ----

function stored() {
  try {
    const w = JSON.parse(localStorage.getItem(SIZE) || "null");
    if (w && w.ctx > 0 && w.card > 0) return { ctx: +w.ctx, card: +w.card };
  } catch { /* no storage, or not ours */ }
  return { ...WIDE };
}
function keep() {
  try { localStorage.setItem(SIZE, JSON.stringify(want)); } catch { /* no storage: for this time only */ }
}
function roomOf(stage) {
  const cs = getComputedStyle(stage);
  return stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
}

// the widths asked for, as they fit the room: too wide — both narrow in the same proportion, neither under its least;
// solo — the card with no context next to it
function fitted(room) {
  const g = m.gap;
  let ctx = want.ctx, card = want.card;
  if (ctx + g + card > room) { const k = (room - g) / (ctx + card); ctx *= k; card *= k; }
  // whole pixels, never past the room: both halves rounded up would be a pixel too wide
  ctx = Math.round(Math.max(LEAST.ctx, ctx));
  card = Math.max(LEAST.card, Math.min(Math.round(card), Math.floor(room - g - ctx)));
  ctx = Math.max(LEAST.ctx, Math.min(ctx, Math.floor(room - g - card)));   // the card at its least: the context gives way
  return { ctx, card, solo: Math.max(LEAST.card, Math.min(Math.round(want.card), Math.floor(room))), room };
}

// the widths onto the open mode: the layer's CSS variables (ask-gallery.css), the shown handles' values
function layout() {
  if (!m) return;
  const f = m.fit = fitted(m.width), sig = `${f.ctx}|${f.card}|${f.solo}`;
  if (m.fitSig !== sig) {
    m.fitSig = sig;
    m.layer.style.setProperty("--ag-ctx-w", `${f.ctx}px`);
    m.layer.style.setProperty("--ag-card-w", `${f.card}px`);
    m.layer.style.setProperty("--ag-solo-w", `${f.solo}px`);
  }
  const s = m.slide, pair = !!s?.classList.contains("with-ctx");
  if (!s) return;
  value(s.querySelector(".ag-split"), f.ctx, LEAST.ctx, f.ctx + f.card - LEAST.card);
  value(s.querySelector(".ag-edge"), pair ? f.card : f.solo, LEAST.card, pair ? f.room - m.gap - f.ctx : f.room);
}
function value(h, now, min, max) {
  for (const [k, v] of [["aria-valuenow", now], ["aria-valuemin", min], ["aria-valuemax", Math.round(Math.max(min, max))]])
    if (h.getAttribute(k) !== String(v)) h.setAttribute(k, v);
}

// from the widths shown (f), by d px: split — the context takes it from the card, the pair keeps its width; edge — the
// card, the pair stays in the middle. What is shown becomes what is asked for: a move in a narrow window sets the widths
function resize(kind, f, pair, d) {
  const room = Math.floor(m.width);   // now, not when the drag began: a scrollbar may have come meanwhile
  d = Math.round(d);   // whole pixels: the pair's width stays the sum of its parts
  if (kind === "split") {
    const both = f.ctx + f.card, ctx = Math.max(LEAST.ctx, Math.min(f.ctx + d, both - LEAST.card));
    want = { ctx, card: both - ctx };
  } else if (pair) want = { ctx: f.ctx, card: Math.max(LEAST.card, Math.min(f.card + d, room - m.gap - f.ctx)) };
  else want = { ...want, card: Math.max(LEAST.card, Math.min(f.solo + d, room)) };
  layout();
}

// a width handle as the page's own divider (base.css .grip: its look, cursor and the theme's colors), dragged by a mouse or
// a finger, ←/→ (Shift — a bigger step) on the keyboard, a double click — the default widths. split — between the context
// and the card; edge — the card's outer edge: the pair is centered, so it grows by twice the move
function grip(kind) {
  const h = hub.el("div", `grip ag-grip ag-${kind}`);
  h.setAttribute("role", "separator");
  h.setAttribute("aria-orientation", "vertical");
  h.setAttribute("aria-label", kind === "split" ? W.split : W.edge);
  h.title = W.gripHint;
  h.tabIndex = 0;
  const pair = () => h.parentNode.classList.contains("with-ctx");
  let drag = null;
  const end = () => {
    if (held === end) held = null;
    if (!drag) return;
    const moved = drag.moved;
    drag = null;
    h.classList.remove("dragging");
    document.body.classList.remove("resizing");   // the page's own: the col-resize cursor everywhere, no text selected
    if (moved) keep();
  };
  h.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !m?.fit) return;
    e.preventDefault();
    h.setPointerCapture(e.pointerId);
    drag = { x: e.clientX, f: m.fit, pair: pair(), moved: false };
    held = end;
    h.classList.add("dragging");
    document.body.classList.add("resizing");
  });
  h.addEventListener("pointermove", (e) => {
    if (!drag || (!drag.moved && Math.abs(e.clientX - drag.x) <= 3)) return;   // a click with a shaky hand keeps the widths
    drag.moved = true;
    resize(kind, drag.f, drag.pair, (e.clientX - drag.x) * (kind === "edge" ? 2 : 1));
  });
  h.addEventListener("pointerup", end);
  h.addEventListener("lostpointercapture", end);
  h.addEventListener("keydown", (e) => {
    const dir = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    if (!dir || !m?.fit) return;
    e.preventDefault();
    resize(kind, m.fit, pair(), dir * (e.shiftKey ? 64 : 16));
    keep();
  });
  h.addEventListener("dblclick", () => {
    want = { ...WIDE };
    try { localStorage.removeItem(SIZE); } catch { /* no storage */ }
    layout();
  });
  return h;
}

// a finger swipe across the card: left — the next question, right — the previous one; a vertical one scrolls
function swipe(stage) {
  let x0 = null, y0 = 0;
  stage.addEventListener("touchstart", (e) => {
    const t = e.touches[0];
    x0 = e.touches.length === 1 && !e.target.closest("textarea, input[type=text], pre, .code, .ag-ctx, .ag-grip") ? t.clientX : null;
    y0 = t.clientY;
  }, { passive: true });
  stage.addEventListener("touchend", (e) => {
    if (x0 == null) return;
    const t = e.changedTouches[0], dx = t.clientX - x0, dy = t.clientY - y0;
    x0 = null;
    if (Math.abs(dx) > 48 && Math.abs(dx) > Math.abs(dy) * 1.5) step(dx < 0 ? 1 : -1);
  }, { passive: true });
}

// a field that uses ←/→ itself (a checkbox does not); a control that Space presses (a width handle is not one: Space on it
// must not reach the page's voice message)
const typing = (n) => (/^(INPUT|TEXTAREA|SELECT)$/.test(n?.tagName || "") && n.type !== "checkbox") || !!n?.isContentEditable;
const pressable = (n) => (typing(n) || /^(INPUT|BUTTON)$/.test(n?.tagName || "")
  || !!n?.matches?.('[role=button], [tabindex]:not([tabindex="-1"])')) && !n.classList.contains("ag-grip");

// keys of the mode go before the page's: Esc leaves the mode (the page's Esc would close the question without an
// answer), ←/→ move between questions, Space outside a field does not start a voice message to the session
// behind. A recording in progress keeps its own Esc; the image viewer (lightbox) runs before us and keeps its keys
function keys(e) {
  if (!m || e.metaKey || e.ctrlKey || e.altKey || document.querySelector("dialog[open]")) return;   // a dialog keeps its keys
  if (e.key === "Escape") {
    if (V.rec || V.opening) return;
    if (e.isComposing) return void e.stopImmediatePropagation();   // the IME takes it; the page must not close the question
    e.preventDefault();
    e.stopImmediatePropagation();
    close();
  } else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !typing(document.activeElement)
    && !document.activeElement?.classList.contains("ag-grip")) {   // a width handle: its own arrows
    e.preventDefault();
    e.stopImmediatePropagation();
    step(e.key === "ArrowRight" ? 1 : -1, true);
  } else if (e.code === "Space" && !pressable(document.activeElement)) {
    e.stopImmediatePropagation();
  }
}

// the entry in the open session's header (session.header): only while the session has open questions — the question
// glyph of a session row waiting for you (sidebar.js, "?") in the same color, the button edged with it; the number is
// in its label. The root is per session, so is the button
function headButton(root, snap, ctx) {
  const s = ctx.session, n = asks(s).length;
  let b = root.firstChild;
  if (!b) {
    b = hub.el("button", "btn small ag-open");
    b.type = "button";
    const g = hub.el("span", "glyph ag-q", "?");
    g.setAttribute("aria-hidden", "true");
    b.append(g, hub.el("span", "ag-t", W.open));
    b.addEventListener("click", () => open(s.name, b));
    root.append(b);
  }
  b.hidden = !n;
  const label = W.openN(n);
  if (b.title !== label) { b.title = label; b.setAttribute("aria-label", label); }
}

export default function register(api) {
  hub = api;
  W = WORDS[hub.lang] || WORDS.en;
  hub.addStyle("web/ask-gallery.css");
  hub.addSlot("session.header", { id: "open", order: 50, render: headButton });
  addEventListener("keydown", keys, true);
  addEventListener("popstate", () => { if (m && history.state?.[MARK] !== m.name) close(true); });
  addEventListener("keyup", (e) => { if (m && e.code === "Space" && !pressable(document.activeElement) && !document.querySelector("dialog[open]")) e.stopImmediatePropagation(); }, true);
  let kept = null;
  try { kept = sessionStorage.getItem(KEEP); } catch { /* no storage */ }
  if (kept) {   // the tab reloaded in the mode (a hub update): back into it once the snapshot is here
    const wait = setInterval(() => {
      if (!hub.snapshot()) return;
      clearInterval(wait);
      if (history.state?.[MARK] === kept) open(kept);   // unless Back already left the mode's entry
      else try { sessionStorage.removeItem(KEEP); } catch { /* no storage */ }
    }, 100);
  }
}
