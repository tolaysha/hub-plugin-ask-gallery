// What the "context" block next to a question shows, from the asking session's feed rows (/api/history, the page's
// timeline): no DOM, so the rule can be run on a journal outside the page too (tests/test_chain.py).
//
// A turn starts with messages the session took (not a line passed to a mini-hub, not one typed in the middle of a turn;
// messages taken one after another with nothing of the session's between them are one turn, as the page's feed counts
// them), with a terminal line, or with the owner's answer to a question form given inside a running turn. The owner's
// answer to a card comes to the session as a message of its own (answer_to: "q<seq of the question>", the same seq as the
// "↳" answer row; a card closed without an answer has no "↳" row and is not an answer).
// The block is the session's text nearest to the card in the turn it was asked in: its last text right before the card
// (after the previous tool or card), or, with none there, the turn's last text after the card (its summary, drawn as it
// comes). Earlier pieces of the turn and other turns stay out. When the turn was started by the owner's answer to an
// earlier card, that question and the answer go above the text; an answer given turns earlier belongs to another
// question, not to this one.

const WAITING = ["queued", "typing", "aside"];
const waits = (it, msgs) => it.kind === "in" && !it.relayed && WAITING.includes((msgs[it.id] || {}).state);

// the rows in the feed's order (main.js feedList): a message where the session took it (delivery time); queued ones are
// not in the feed yet
export function order(rows, msgs = {}) {
  const at = (it) => (it.kind === "in" && !it.relayed && (msgs[it.id] || {}).delivered_at) || it.ts;
  const shown = rows.filter((it) => !waits(it, msgs)).sort((a, b) => a.seq - b.seq);
  return shown.map((it, i) => [it, i]).sort((a, b) => at(a[0]) - at(b[0]) || a[1] - b[1]).map(([it]) => it);
}

const said = (x) => x.kind === "out" && !x.error && String(x.text || "").trim() !== "" && String(x.text).trim() !== "—";
const owner = (x) => (x.from ? x.from.kind === "owner" : !x.sender);
const work = (x) => x.kind === "out" || x.kind === "tool";   // the session's own rows: they end a run of messages

// what the rows say about answers: the seqs of the core's messages that carry an answer (relays), the seqs of "↳" rows
// (answers), the question forms by request
function facts(rows) {
  const forms = new Set(rows.filter((x) => x.kind === "ask" && x.tool === "AskUserQuestion").map((x) => x.request_id));
  return {
    relays: new Set(rows.filter((x) => x.kind === "in" && x.answer_to).map((x) => x.seq)),
    answers: new Set(rows.filter((x) => x.kind === "answer").map((x) => x.seq)),
    form: (rid) => forms.has(rid),
  };
}

// the kind of a turn by its first row: answer (the owner's answer to a question form), owner (the owner's own words, a
// terminal line), other (someone else's message, a card closed without an answer)
function kindOf(x, f) {
  if (x.kind === "answer") return f.relays.has(x.seq) || !f.form(x.request_id) ? null : "answer";
  if (x.kind === "terminal") return "owner";
  if (x.kind !== "in" || x.relayed || x.midturn) return null;
  if (x.answer_to) return f.answers.has(x.seq) ? "answer" : "other";
  return owner(x) ? "owner" : "other";
}
const RANK = { answer: 3, owner: 2, other: 1 };

// the turns of the rows: [{kind, start: index of the first row (-1: began before the loaded rows), end}]
function turns(list, f) {
  const out = [];
  let cur = { kind: null, start: -1, end: 0, worked: true };
  list.forEach((x, i) => {
    const k = kindOf(x, f);
    if (!k) { if (work(x)) cur.worked = true; return; }
    if (!cur.worked && cur.start >= 0) {   // taken right after the previous message: the same turn
      if (RANK[k] > RANK[cur.kind]) cur.kind = k;
      return;
    }
    cur.end = i;
    out.push(cur);
    cur = { kind: k, start: i, end: 0, worked: false };
  });
  cur.end = list.length;
  out.push(cur);
  return out.filter((t) => t.start >= 0 || t.end > 0);
}

// the session's text nearest to the card at index at in its turn: [] — none
function nearest(list, at, turn) {
  for (let i = at - 1; i > turn.start; i--) {
    const x = list[i];
    if (said(x)) return [x];
    if (x.kind === "ask" || (x.kind === "tool" && x.name !== "AskUserQuestion")) break;   // the card's own call is no boundary
  }
  const after = list.slice(at + 1, turn.end).findLast(said);
  return after ? [after] : [];
}

// the context of the question with request rid: {ask, answer, said, whole} — the earlier question and its answer (both
// null when the question's turn was not started by an answer), the session's text rows, whole: false while the rows may
// begin too late (the turn starts before them: load earlier rows); null — the question's row is not among the rows (yet)
export function context(rows, rid, msgs = {}, more = false) {
  const f = facts(rows), list = order(rows, msgs);
  const at = list.findLastIndex((x) => x.kind === "ask" && x.request_id === rid);
  if (at < 0) return null;
  const ts = turns(list, f), turn = ts.find((t) => t.start <= at && at < t.end);
  const text = nearest(list, at, turn);
  // a turn begun before the loaded rows (kind null), or with their very first row (the run of messages it began with may
  // go on before them), may be an answer's: earlier rows are needed to tell
  if (turn.kind !== "answer") return { ask: null, answer: null, said: text, whole: (turn.kind !== null && turn.start > 0) || !more };
  // the answer: the "↳" row of the core's message (the same seq), or the "↳" row that began the turn
  const head = list.slice(turn.start, turn.end).filter((x) => kindOf(x, f) === "answer" || (x.kind === "in" && x.answer_to));
  // several answers taken in one turn: the latest one led to what the session said
  const relay = head.findLast((x) => x.kind === "in" && x.answer_to && f.answers.has(x.seq));
  const answer = relay ? list.find((x) => x.kind === "answer" && x.seq === relay.seq) || null : head.findLast((x) => x.kind === "answer") || null;
  const qseq = relay ? Number(String(relay.answer_to).replace(/^q/, "")) : null;
  const ask = list.findLast((x, i) => x.kind === "ask" && i < turn.end && x.seq <= (answer?.seq ?? Infinity)
    && (x.seq === qseq || (!!answer && x.request_id === answer.request_id))) || null;
  return { ask, answer, said: text, whole: !!ask || !more };
}
