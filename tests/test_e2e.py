"""«Только вопросы» в настоящем браузере: страница хаба на временном журнале, плагин из этой папки, ответы идут
через настоящую свёртку ядра (core_decides). Живой хаб не трогается.

Запуск — из рабочей копии agents-hub-core (там tests/ и modules/):
  cd <agents-hub-core> && python3.12 -m unittest discover -s ~/hub-ext/ask-gallery/tests -t ~/hub-ext/ask-gallery/tests
Скриншоты — в папку HUB_TEST_ASK_SHOTS, если она задана."""
import os
import sys

sys.path.insert(0, os.getcwd())   # the hub repo: tests/ and core/ come from there
import tests  # noqa: E402,F401 — drops the machine's own HUB_* settings
import json  # noqa: E402
import time  # noqa: E402
from unittest import mock  # noqa: E402

from tests import test_web_e2e as e2e  # noqa: E402

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# animations created while window.__freeze is set stop early (ease-out is mostly done by half time): a screenshot of a card on its way
FREEZE = ("const o = Element.prototype.animate; Element.prototype.animate = function (k, opt) {"
          " const a = o.call(this, k, opt); if (window.__freeze) { a.pause(); a.currentTime = (opt.delay || 0) + opt.duration * 0.15;"
          " (window.__frozen ||= []).push(a); } return a; };")
REDUCED = ("const mm = window.matchMedia.bind(window); window.matchMedia = (q) => q.includes('prefers-reduced-motion')"
           " ? { matches: true, media: q, addEventListener() {}, removeEventListener() {} } : mm(q);"
           " const o = Element.prototype.animate; Element.prototype.animate = function (...a) { window.__anims = (window.__anims || 0) + 1;"
           " (window.__moves ||= []).push(JSON.stringify(a[0]).includes('transform')); return o.apply(this, a); };")
# the context next to the shown card: its rows' text, whether it is visible, where it stands against the card
CTX = ("(() => { const s = document.querySelector('.ag-layer .ag-slide:not([inert])'), c = s?.querySelector('.ag-ctx'); if (!c) return null;"
       " const card = s.querySelector(':scope > .card').getBoundingClientRect(), x = c.getBoundingClientRect(), b = c.querySelector('.ag-ctx-body');"
       " return {hidden: c.hidden, rows: [...b.children].map((r) => (r.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 90)),"
       " left: x.right <= card.left, above: x.bottom <= card.top, inside: x.left >= 0 && x.right <= innerWidth,"
       " scrolls: b.scrollHeight > b.clientHeight + 1 && getComputedStyle(b).overflowY === 'auto', h: Math.round(b.clientHeight),"
       " more: (() => { const m = c.querySelector('.ag-ctx-more'); return m && !m.hidden && getComputedStyle(m).display !== 'none' ? m.textContent : null; })(),"
       " acts: c.querySelectorAll('.reply-btn, .react-add, .quote-jump[role]').length, md: c.querySelectorAll('strong').length}; })()")
# the widths of the shown slide: the context and the card, the handles (their middle, value, role), what is kept
WID = ("(() => { const s = document.querySelector('.ag-layer .ag-slide:not([inert])'); if (!s) return null;"
       " const w = (q) => { const n = s.querySelector(q); return n && n.getClientRects().length ? Math.round(n.getBoundingClientRect().width) : null; };"
       " const g = (q) => { const n = s.querySelector(q); if (!n || !n.getClientRects().length) return null; const r = n.getBoundingClientRect();"
       " return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), now: +n.getAttribute('aria-valuenow'),"
       " max: +n.getAttribute('aria-valuemax'), role: n.getAttribute('role'), tab: n.tabIndex, cursor: getComputedStyle(n).cursor}; };"
       " const x = s.getBoundingClientRect();"
       " return {ctx: w(':scope > .ag-ctx'), card: w(':scope > .card'), split: g('.ag-split'), edge: g('.ag-edge'),"
       " kept: JSON.parse(localStorage.getItem('ask-gallery.widths')), left: Math.round(x.left), right: Math.round(x.right), vw: innerWidth}; })()")
SPLIT = ".ag-layer .ag-slide:not([inert]) .ag-split"
EDGE = ".ag-layer .ag-slide:not([inert]) .ag-edge"
# a point to drag a handle to: the mouse goes to the middle of this 1px mark
TO = ("(() => { let t = document.getElementById('ag-to'); if (!t) { t = document.createElement('div'); t.id = 'ag-to';"
      " t.style.cssText = 'position: fixed; width: 1px; height: 1px; pointer-events: none'; document.body.append(t); }"
      " t.style.left = '%dpx'; t.style.top = '%dpx'; return 1; })()")
OPEN = ".slot-session-header .ag-open:not([hidden])"
LAYER = ".ag-layer"
COUNT = "document.querySelector('.ag-layer .ag-count')?.textContent"
CUR = "document.querySelector('.ag-layer .ag-slide:not([inert]) legend')?.textContent"
ONE = "document.querySelectorAll('.ag-layer .ag-slide').length === 1"   # the move is over: only the shown slide is left


def load_tests(loader, standard, pattern):   # only this file's tests, not the inherited page suite
    return loader.loadTestsFromNames([f"{__name__}.Gallery.{n}" for n in sorted(Gallery.__dict__) if n.startswith("test_")])


class Gallery(e2e.PageInChrome):
    def setUp(self):
        super().setUp()
        cfg = os.path.join(self.state, "hub.json")
        with open(cfg, "w") as f:
            json.dump({"extensions": {"ask-gallery": {"path": PLUGIN, "web": "web/main.js"}}}, f)
        env = mock.patch.dict(os.environ, {"HUB_CONFIG": cfg})
        env.start()
        self.addCleanup(env.stop)
        self.core_decides()
        self.shots = os.environ.get("HUB_TEST_ASK_SHOTS") or self.state
        os.makedirs(self.shots, exist_ok=True)
        self.ev("session.requested", "backend", session_id="s-b", cwd="/w", channel="cli", owner=True, icon="🛠️")
        self.ev("session.started", "backend", session_id="s-b")
        self.ev("turn.started", "backend", marker=None, prompt_head="x")

    def ask(self, rid, *questions, multi=False, who="backend", ts=None):
        self.j.append("permission.requested", who, {"request_id": rid, "tool": "AskUserQuestion", "interactive": True, "input": {
            "questions": [{"question": q, "multiSelect": multi, "header": "Выбор",
                           "options": [{"label": "Да", "description": "Делаем сейчас"}, {"label": "Нет"},
                                       {"label": "Позже", "description": "Вернёмся на следующей неделе"}]}
                          for q in questions]}}, ts=ts)

    def session(self, name, icon):
        self.ev("session.requested", name, session_id=f"s-{name}", cwd="/w", channel="cli", owner=True, icon=icon)
        self.ev("session.started", name, session_id=f"s-{name}")
        self.ev("turn.started", name, marker=None, prompt_head="x")

    def page(self, *steps):
        # cdp.mjs returns the last value of an "until" that timed out: here every wait must come true
        got = super().page(*steps)
        for step, out in zip(steps, got):
            if "until" in step:
                self.assertTrue(out["until"], f"не дождался: {step['until']}")
        return got

    def shot(self, name, **kw):
        return {"shot": os.path.join(self.shots, name), "width": 1300, "height": 860, **kw}

    def opened(self, *more, init=None, at="backend"):
        go = {"go": f"http://127.0.0.1:{self.port}/#/s/{at}", **({"init": init} if init else {})}
        return self.page(go, {"until": f"!!document.querySelector('{OPEN}')", "ms": 15000},
                         {"eval": f"document.querySelector('{OPEN}').click(), 1"},
                         {"until": f"!!document.querySelector('{LAYER} .ag-slide')"}, *more)

    def taken(self, *rids, who="backend"):
        end = time.time() + 8   # the card leaves at once, the core records the answer a moment later
        while any(r in self.pending(who) for r in rids) and time.time() < end:
            time.sleep(0.05)
        for r in rids:
            self.assertNotIn(r, self.pending(who))

    def pending(self, who="backend"):
        from core import journal, reducer   # the core's own fold of the test journal
        st = reducer.fold(reducer.empty(), journal.read(self.j.path))
        s = st["sessions"][who]   # a question form is an ask of the session; a tool permission — its pending
        return [r["request_id"] for r in (s.get("asks") or []) + (s.get("pending") or [])]

    def test_the_gallery_moves_answers_and_leaves_with_the_last_one(self):
        self.ask("r1", "Сервис отвечает медленно после выката. Откатываем выпуск?")
        self.ask("r2", "Какие проверки добавить в CI?", multi=True)
        self.ask("r3", "Как назовём новую очередь?")
        got = self.opened({"eval": COUNT}, {"eval": "document.querySelectorAll('.feed .ask-card').length"},
                          {"eval": "document.querySelector('.ag-layer .ag-who').textContent"},
                          {"eval": "document.getElementById('app').inert"},
                          self.shot("gallery-light.png", theme="light"),
                          {"key": "ArrowRight"}, {"until": f"{COUNT} === '2 из 3'"}, {"eval": CUR},
                          self.shot("gallery-dark.png", theme="dark"),
                          {"key": "ArrowLeft"}, {"until": f"{COUNT} === '1 из 3'"},
                          {"key": "ArrowLeft"}, {"eval": COUNT},   # the first one: nowhere further left
                          {"eval": "document.querySelector('.ag-prev').disabled"}, init=FREEZE)
        self.assertEqual(got[4]["eval"], "1 из 3")
        self.assertEqual(got[5]["eval"], 3)                            # the page's feed keeps its cards: nothing is folded
        self.assertEqual(got[6]["eval"].strip(), "🛠️ backend")
        self.assertTrue(self.page({"eval": "document.querySelector('.ag-layer .ag-bar').hidden"})[0]["eval"])   # one session: no switcher
        self.assertTrue(got[7]["eval"])                                 # the page behind is out of reach
        self.assertIn("Какие проверки", got[11]["eval"])
        self.assertEqual(got[-2]["eval"], "1 из 3")
        self.assertTrue(got[-1]["eval"])
        # a tap on an option answers the single-choice card: it goes up and fades, the next one comes from the right
        got = self.page({"eval": "window.__freeze = true, document.querySelector('.ag-layer .ag-slide:not([inert]) label.opt').click(), 1"},
                        {"until": "(window.__frozen || []).length >= 2", "ms": 8000},
                        self.shot("gallery-answer-mid.png", theme="light"),
                        {"eval": "window.__freeze = false, window.__frozen.forEach((a) => a.play()), 1"},
                        {"until": f"{COUNT} === '1 из 2'", "ms": 8000}, {"eval": CUR},
                        {"until": "document.querySelectorAll('.ag-layer .ag-slide').length === 1"})
        self.assertIn("Какие проверки", got[5]["eval"])
        self.assertTrue(got[-1]["until"])                               # the answered card is gone from the stage
        self.taken("r1")                                                # the core took the answer
        # several options and "Answer"; then a question arrives while the mode is open — it joins the end
        got = self.page({"eval": "(() => { const s = document.querySelector('.ag-layer .ag-slide:not([inert])');"
                                 " const b = s.querySelectorAll('input[type=checkbox]'); b[0].click(); b[2].click();"
                                 " s.querySelector('button[type=submit]').click(); return 1; })()"},
                        {"until": f"{COUNT} === '1 из 1'", "ms": 8000})
        self.assertTrue(got[-1]["until"])
        self.taken("r2")
        self.ask("r4", "Переносим окно работ на субботу?")
        got = self.page({"until": f"{COUNT} === '1 из 2'", "ms": 8000}, {"eval": CUR})
        self.assertIn("Как назовём", got[-1]["eval"])                   # the shown card stays; the new one is second
        # a custom answer (Enter), then × on the last one — closed without an answer, it leaves too
        got = self.page({"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"},
                        {"typed": "orders-retry"}, {"key": "Enter"},
                        {"until": f"{COUNT} === '1 из 1'", "ms": 8000}, {"eval": CUR},
                        {"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) .card-x').click(), 1"},
                        {"until": f"!document.querySelector('{LAYER}')", "ms": 8000},
                        {"eval": "[document.getElementById('app').inert, document.activeElement?.id]"})
        self.assertIn("Переносим окно", got[4]["eval"])
        self.assertEqual(got[-1]["eval"], [False, "msg"])               # back in the hub: the session's field
        self.taken("r3", "r4")
        # the session asks again: the mode opens on it; Esc leaves the mode and does not close the question
        self.page({"until": f"!document.querySelector('{OPEN}')", "ms": 8000})   # the core took the closing: no button
        self.ask("r5", "Включаем новый кэш для всех?")
        got = self.page({"until": f"!!document.querySelector('{OPEN}')", "ms": 8000}, {"eval": f"document.querySelector('{OPEN}').click(), 1"},
                        {"until": f"{COUNT} === '1 из 1'", "ms": 8000},
                        {"key": "Escape"}, {"until": f"!document.querySelector('{LAYER}')"},
                        {"eval": "document.getElementById('app').inert"},
                        {"eval": "document.activeElement?.classList.contains('ag-open')"})
        self.assertFalse(got[5]["eval"])
        self.assertTrue(got[6]["eval"])                                 # the focus is back on the header button
        self.assertEqual(self.pending(), ["r5"])

    def test_a_phone_swipes_and_a_reload_keeps_the_mode(self):
        self.ask("r1", "Первый вопрос: длинный контекст про выпуск, правку доставки и новую вкладку. Публикуем?")
        self.ask("r2", "Второй вопрос?")
        swipe = ("(() => { const st = document.querySelector('.ag-layer .ag-stage'), t = (x) => new Touch({identifier: 1, target: st, clientX: x, clientY: 300});"
                 " st.dispatchEvent(new TouchEvent('touchstart', {touches: [t(%d)], bubbles: true}));"
                 " st.dispatchEvent(new TouchEvent('touchend', {changedTouches: [t(%d)], bubbles: true})); return 1; })()")
        got = self.opened({"touch": True}, self.shot("gallery-phone-light.png", width=390, height=780, theme="light"),
                          {"eval": "(() => { const r = document.querySelector('.ag-layer .ag-slide .card').getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth; })()"},
                          {"eval": swipe % (300, 100)}, {"until": f"{COUNT} === '2 из 2'"},
                          {"eval": swipe % (100, 300)}, {"until": f"{COUNT} === '1 из 2'"},
                          self.shot("gallery-phone-dark.png", width=390, height=780, theme="dark"))
        self.assertTrue(got[6]["eval"])                                 # the card fits the phone width
        self.assertTrue(got[8]["until"])
        self.assertTrue(got[10]["until"])
        got = self.page({"touch": False}, {"eval": "history.length"}, {"eval": "location.reload(), 1"},
                        {"until": f"{COUNT} === '1 из 2'", "ms": 15000}, {"eval": "history.length"})
        self.assertEqual(got[-1]["eval"], got[1]["eval"])               # the mode came back on its own history entry

    def test_reduced_motion_swaps_cards_without_animation(self):
        self.ask("r1", "Первый?")
        self.ask("r2", "Второй?")
        got = self.opened({"eval": "window.__anims = 0"}, {"key": "ArrowRight"}, {"until": f"{COUNT} === '2 из 2'"},
                          {"eval": "document.querySelectorAll('.ag-layer .ag-slide').length"}, {"eval": "window.__anims"},
                          init=REDUCED)
        self.assertEqual(got[-2]["eval"], 1)                            # the old card is removed at once
        self.assertEqual(got[-1]["eval"], 0)
        # an answer still shows that the card left — by fading, without movement
        got = self.page({"eval": "window.__moves = [], document.querySelector('.ag-layer .ag-slide:not([inert]) label.opt').click(), 1"},
                        {"until": f"{COUNT} === '1 из 1'", "ms": 8000}, {"eval": "window.__moves"},
                        {"eval": "window.__moves = [], document.querySelector('.ag-layer .ag-slide:not([inert]) label.opt').click(), 1"},
                        {"until": f"!document.querySelector('{LAYER}')", "ms": 8000}, {"eval": "window.__moves"})
        self.assertEqual(got[2]["eval"], [False, False])
        self.assertEqual(got[-1]["eval"], [False])                       # the last one fades, then the mode closes

    # the slides' own moves stopped at half time: where each slide is (its transform), how long its move is, its opacity
    MID = ("(() => { const out = []; for (const s of document.querySelectorAll('.ag-layer .ag-stage > .ag-slide')) {"
           " const as = s.getAnimations().filter((a) => a.effect.getComputedTiming().endTime !== Infinity);"
           " for (const a of as) { a.pause(); a.currentTime = a.effect.getComputedTiming().duration / 2; }"
           " const t = new DOMMatrix(getComputedStyle(s).transform);"
           " out.push({leaving: s.inert, n: as.length, ms: as.map((a) => a.effect.getComputedTiming().duration),"
           " delay: as.map((a) => a.effect.getComputedTiming().delay), x: Math.round(t.e), y: Math.round(t.f),"
           " op: +getComputedStyle(s).opacity, wide: document.querySelector('.ag-layer .ag-stage').clientWidth}); }"
           " return out; })()")
    PLAY = "document.querySelectorAll('.ag-layer .ag-slide').forEach((s) => s.getAnimations().forEach((a) => a.play())), 1"
    # the most slides the stage ever held at once
    MOST = ("(() => { const st = document.querySelector('.ag-layer .ag-stage'); let n = st.children.length; window.__most = n;"
            " new MutationObserver((rs) => { for (const r of rs) { n += r.addedNodes.length - r.removedNodes.length;"
            " window.__most = Math.max(window.__most, n); } }).observe(st, {childList: true}); return 1; })()")

    def mid(self, got):
        out, inn = [x for x in got if x["leaving"]], [x for x in got if not x["leaving"]]
        self.assertEqual((len(out), len(inn)), (1, 1), got)
        return out[0], inn[0]

    def test_a_move_slides_both_cards_across_the_stage_together_like_a_photo_gallery(self):
        for n, q in enumerate(("Первый?", "Второй?", "Третий?", "Четвёртый?", "Пятый?"), 1):
            self.ask(f"r{n}", q)
        got = self.opened({"eval": self.MOST}, {"key": "ArrowRight"}, {"eval": self.MID},
                          self.shot("move-mid-light.png", theme="light"), self.shot("move-mid-dark.png", theme="dark"),
                          {"eval": self.PLAY}, {"until": f"{COUNT} === '2 из 5' && {ONE}"},
                          {"eval": "document.querySelector('.ag-prev').click(), 1"}, {"eval": self.MID}, {"eval": self.PLAY},
                          {"until": f"{COUNT} === '1 из 5' && {ONE}"})
        out, inn = self.mid(got[6]["eval"])
        # → : the shown one goes out to the left, the next one comes in from the right, both at once and all the way
        self.assertLess(out["x"], -100)
        self.assertGreater(inn["x"], 100)
        self.assertEqual(inn["x"] - out["x"], out["wide"])               # one strip: always the stage's width apart
        self.assertEqual((out["y"], inn["y"], out["op"], inn["op"]), (0, 0, 1, 1))   # sideways only, no fading on the way
        for x in (out, inn):
            self.assertEqual(x["n"], 1)
            self.assertGreaterEqual(x["ms"][0], 380)
            self.assertLessEqual(x["ms"][0], 500)
            self.assertEqual(x["delay"], [0])                             # they start together
        out, inn = self.mid(got[12]["eval"])                             # the "previous" button: the other way
        self.assertGreater(out["x"], 100)
        self.assertLess(inn["x"], -100)
        # quick presses and a held key: each press finishes the move under way, the order holds, nothing stacks up
        hold = ("(() => { for (let i = 0; i < 12; i++) window.dispatchEvent(new KeyboardEvent('keydown',"
                " {key: 'ArrowRight', code: 'ArrowRight', repeat: i > 0, bubbles: true, cancelable: true})); return 1; })()")
        got = self.page({"key": "ArrowRight"}, {"key": "ArrowRight"}, {"until": f"{COUNT} === '3 из 5' && {ONE}"},
                        {"until": f"{CUR}?.includes('Третий?')"}, {"eval": hold},
                        {"until": f"{COUNT} === '5 из 5' && {ONE}"}, {"until": f"{CUR}?.includes('Пятый?')"},
                        {"eval": "window.__most"})
        self.assertLessEqual(got[-1]["eval"], 2)

    def test_an_answered_card_flies_up_and_the_next_comes_in_sideways(self):
        self.ask("r1", "Первый?")
        self.ask("r2", "Второй?")
        self.ask("r3", "Третий?")
        pick = "document.querySelector('.ag-layer .ag-slide:not([inert]) label.opt').click(), 1"
        got = self.opened({"eval": pick}, {"eval": self.MID},
                          self.shot("answer-mid-light.png", theme="light"), self.shot("answer-mid-dark.png", theme="dark"),
                          {"eval": self.PLAY}, {"until": f"{COUNT} === '1 из 2' && {ONE}", "ms": 8000},
                          {"until": f"{CUR}?.includes('Второй?')"})
        out, inn = self.mid(got[5]["eval"])
        self.assertEqual(out["x"], 0)
        self.assertLess(out["y"], -50)                                   # the answered one goes up
        self.assertGreater(inn["x"], 100)                                # the next one comes from the right
        self.assertEqual(inn["op"], 1)
        self.assertGreaterEqual(min(out["ms"] + inn["ms"]), 380)
        # the last in the list answered: the one before it comes from the left
        got = self.page({"key": "ArrowRight"}, {"until": f"{COUNT} === '2 из 2' && {ONE}"}, {"eval": pick}, {"eval": self.MID},
                        {"eval": self.PLAY}, {"until": f"{COUNT} === '1 из 1' && {ONE}", "ms": 8000}, {"until": f"{CUR}?.includes('Второй?')"})
        out, inn = self.mid(got[3]["eval"])
        self.assertLess(out["y"], -50)
        self.assertLess(inn["x"], -100)
        # the last answer: it flies up, and the mode closes once it is gone, not before and not much later
        gone = ("window.__gone = null, new MutationObserver(() => { if (window.__gone == null && !document.querySelector('.ag-layer'))"
                " window.__gone = performance.now(); }).observe(document.body, {childList: true}), 1")
        flying = ("(() => { const s = document.querySelector('.ag-layer .ag-slide[inert]'); const a = s?.getAnimations()[0];"
                  " return a ? {up: JSON.stringify(a.effect.getKeyframes()).includes('translateY(-'), ms: a.effect.getComputedTiming().duration} : null; })()")
        got = self.page({"eval": gone}, {"eval": "window.__click = performance.now(), " + pick}, {"eval": flying},
                        {"until": f"!document.querySelector('{LAYER}')", "ms": 8000}, {"eval": "Math.round(window.__gone - window.__click)"})
        self.assertTrue(got[2]["eval"] and got[2]["eval"]["up"], got[2]["eval"])
        self.assertGreaterEqual(got[-1]["eval"], got[2]["eval"]["ms"] - 20)
        self.assertLess(got[-1]["eval"], 2000)
        self.taken("r1", "r2", "r3")

    # every frame from the answer until the answered slide is gone: what the leaving card looks like
    FRAMES = ("window.__rec = []; window.__h = document.querySelector('.ag-layer .ag-slide:not([inert]) > .card').getBoundingClientRect().height;"
              " (function tick() { const st = document.querySelector('.ag-layer .ag-stage'); if (!st) return void (window.__done = true);"
              " for (const s of st.children) { const c = s.querySelector(':scope > .card'), l = c.querySelector('.sent-line');"
              " window.__rec.push({leaving: s.inert, mine: !!c.dataset.sending, sent: c.classList.contains('sent'), line: !!l && l.getClientRects().length > 0,"
              " h: Math.round(c.getBoundingClientRect().height), checked: c.querySelectorAll('input:checked').length,"
              " text: c.querySelector('textarea.other')?.value || '', tint: (() => { const p = c.querySelector('.opt.pick:has(input:checked)'),"
              " q = c.querySelector('.opt.pick:not(:has(input:checked))'); return !!p && !!q && getComputedStyle(p).backgroundColor !== getComputedStyle(q).backgroundColor; })()}); }"
              " if ([...st.children].some((x) => x.inert) || !window.__rec.some((r) => r.leaving)) requestAnimationFrame(tick); else window.__done = true; })();")

    def frames(self, act):
        got = self.page({"eval": "(() => { window.__done = false; " + self.FRAMES + " " + act + "; return 1; })()"},
                        {"until": "window.__done", "ms": 8000}, {"eval": "[window.__h, window.__rec.filter((r) => r.leaving || r.mine)]"})
        h, rec = got[-1]["eval"]
        self.assertGreater(len(rec), 3)                                   # the answered card, frame by frame from the click
        for r in rec:
            self.assertFalse(r["sent"] or r["line"], r)                  # never the receipt line "Your answer: … — sending"
            self.assertLessEqual(abs(r["h"] - round(h)), 1, r)           # never folded: the card as it was answered
        return rec

    def test_an_answer_leaves_as_it_was_given_without_the_receipt_line(self):
        self.ask("r1", "Какие проверки добавить в CI?", multi=True)
        self.ask("r2", "Откатываем выпуск?")
        self.ask("r3", "Как назовём новую очередь?")
        self.ask("r4", "Последний?")
        self.opened()
        rec = self.frames("const s = document.querySelector('.ag-layer .ag-slide:not([inert])'), b = s.querySelectorAll('input[type=checkbox]');"
                          " b[0].click(); b[2].click(); s.querySelector('button[type=submit]').click()")
        self.assertTrue(all(r["checked"] == 2 for r in rec))             # with what was picked
        self.page({"until": f"{CUR}?.includes('Откатываем')", "ms": 8000})
        rec = self.frames("document.querySelector('.ag-layer .ag-slide:not([inert]) label.opt').click()")
        self.assertTrue(all(r["checked"] == 1 and r["tint"] for r in rec))   # a tapped option keeps its tint
        self.page({"until": f"{CUR}?.includes('Как назовём')", "ms": 8000},
                  {"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"}, {"typed": "orders-retry"})
        rec = self.frames("document.querySelector('.ag-layer .ag-slide:not([inert]) form').requestSubmit()")
        self.assertTrue(all(r["text"] == "orders-retry" for r in rec))   # with the typed answer
        # the last one: it leaves the same way while the mode closes
        self.page({"until": f"{CUR}?.includes('Последний?')", "ms": 8000})
        self.frames("document.querySelector('.ag-layer .ag-slide:not([inert]) label.opt').click()")
        self.page({"until": f"!document.querySelector('{LAYER}')", "ms": 8000})
        self.taken("r1", "r2", "r3", "r4")

    # the answers wait until the test lets them go (__release): then the core refuses them, or they go on to it (__pass)
    HOLD = ("window.__held = []; window.__pass = false; const f = window.fetch; window.fetch = (u, o) => String(u).includes('/api/answer')"
            " ? new Promise((ok) => window.__held.push(() => ok(window.__pass ? f(u, o)"
            " : new Response(JSON.stringify({error: 'вопрос уже закрыт'}), {status: 409})))) : f(u, o);"
            " window.__release = () => { const n = window.__held.length; window.__held.splice(0).forEach((go) => go()); return n; };")

    def test_a_refused_answer_brings_its_card_back_whole_with_the_reason(self):
        # the card flies away at once, the refusal comes later (during the flight, or after it): the card is shown again,
        # whole, with the reason — unless the owner is typing in another card, then the reason is in the header
        self.ask("r1", "Первый?")
        self.ask("r2", "Второй?")
        self.ask("r3", "Третий?")
        card = ("(() => { const c = document.querySelector('.ag-layer .ag-slide:not([inert]) > .card');"
                " return [c.querySelector('legend').textContent.trim(), c.classList.contains('sent'), !!c.querySelector('.sent-line'),"
                " c.querySelector('.error-text')?.textContent, !!c.dataset.sending]; })()")
        pick = "document.querySelector('.ag-layer .ag-slide:not([inert]) label.opt').click(), 1"
        got = self.opened({"eval": pick}, {"eval": "window.__release()"},   # while it flies
                          {"until": f"{COUNT} === '3 из 3' && {ONE}", "ms": 8000}, {"eval": card}, init=self.HOLD)
        self.assertEqual(got[5]["eval"], 1)
        self.assertEqual(got[-1]["eval"], ["Первый?", False, False, "Ответ не отправлен: вопрос уже закрыт", False])   # at the end now
        got = self.page({"eval": pick}, {"until": f"{COUNT} === '2 из 2' && {ONE}", "ms": 8000}, {"eval": "window.__release()"},
                        {"until": f"{COUNT} === '3 из 3' && {ONE}", "ms": 8000}, {"eval": card})
        self.assertEqual(got[2]["eval"], 1)
        self.assertEqual(got[-1]["eval"][0], "Первый?")                   # after its flight too
        # typing in another card: the card waits at the end of the list, the reason is in the header
        got = self.page({"key": "ArrowLeft"}, {"key": "ArrowLeft"}, {"until": f"{COUNT} === '1 из 3' && {CUR}?.includes('Второй?') && {ONE}"},
                        {"eval": pick}, {"until": f"{COUNT} === '1 из 2' && {CUR}?.includes('Третий?') && {ONE}", "ms": 8000},
                        {"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"}, {"typed": "мой текст"},
                        {"eval": "window.__release()"}, {"until": f"{COUNT} === '1 из 3'", "ms": 8000},
                        {"until": "document.querySelector('.ag-layer .ag-say')?.textContent.includes('вопрос уже закрыт')", "ms": 8000},
                        {"eval": f"[{CUR}, document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').value]"})
        self.assertIn("Третий?", got[-1]["eval"][0])
        self.assertEqual(got[-1]["eval"][1], "мой текст")
        self.assertEqual(sorted(self.pending()), ["r1", "r2", "r3"])

    def test_a_typed_answer_on_its_way_when_the_question_closes_elsewhere_freezes_with_the_text(self):
        self.ask("r1", "Как назовём очередь?")
        self.ask("r2", "Второй?")
        got = self.opened({"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"},
                          {"typed": "orders-retry"}, {"key": "Enter"},
                          {"until": f"{COUNT} === '1 из 1' && {CUR}?.includes('Второй?')", "ms": 8000}, init=self.HOLD)
        self.ev("permission.answered", "backend", request_id="r1", behavior="allow", channel="telegram", owner=True,
                answers={"Как назовём очередь?": "Да"})
        got = self.page({"until": f"{COUNT} === '1 из 2'", "ms": 8000}, {"eval": "window.__release()"},
                        {"key": "ArrowRight"}, {"until": f"{COUNT} === '2 из 2' && {ONE}"},
                        {"eval": "(() => { const c = document.querySelector('.ag-layer .ag-slide:not([inert]) > .card');"
                                 " return [c.classList.contains('frozen'), c.querySelector('textarea.other').value, !!c.querySelector('.frozen-bar')]; })()"})
        self.assertEqual(got[1]["eval"], 1)
        self.assertEqual(got[-1]["eval"], [True, "orders-retry", True])   # the typed text is kept, as on the page's feed
        self.assertEqual(self.pending(), ["r2"])

    def test_a_theme_with_an_endless_animation_in_the_card_does_not_stop_the_move(self):
        # a theme (unix-terminal) blinks the caret of every field with an infinite CSS animation: finishing it throws, and
        # the counter moved while the card on screen stayed the first one
        self.ask("r1", "Первый?")
        self.ask("r2", "Второй?")
        self.ask("r3", "Третий?")
        blink = ("(() => { const s = document.createElement('style'); s.textContent = '@keyframes ag-blink { 50% { caret-color: transparent; } }"
                 " textarea, input[type=text] { animation: ag-blink 1s steps(1, end) infinite; }'; document.head.append(s); return 1; })()")
        self.opened({"eval": blink},
                    {"key": "ArrowRight"}, {"until": f"{COUNT} === '2 из 3'"}, {"until": f"{CUR}?.includes('Второй?')"},
                    {"eval": "document.querySelector('.ag-next').click(), 1"}, {"until": f"{COUNT} === '3 из 3'"},
                    {"until": f"{CUR}?.includes('Третий?')"},
                    {"until": "document.querySelectorAll('.ag-layer .ag-slide').length === 1", "ms": 3000})   # the old card slid out

    def test_the_banner_line_stays_readable_on_a_light_theme_with_a_light_red(self):
        # a light theme whose red is light (an installed one: 3.6:1 on white): the page's banner repeated in the header
        # is small text and needs 4.5:1
        os.makedirs(os.path.join(self.state, "themes"), exist_ok=True)   # own themes: next to hub.json
        with open(os.path.join(self.state, "themes", "light-red.json"), "w") as f:
            json.dump({"name": "Светлая", "dark": False, "colors": {"background": "#ffffff", "foreground": "#27272a", "card": "#ffffff",
                                                                    "primary": "#4f6cf6", "muted-foreground": "#62626b", "destructive": "#ef4e4e"}}, f)
        self.ask("r1", "Первый?")
        pick = ("(() => { window.__t = null; fetch('/api/themes').then((r) => r.json()).then((j) => { const t = j.themes.find((x) => x.theme.name === 'Светлая');"
                " localStorage.setItem('hub.theme', JSON.stringify({id: t.id, theme: t.theme})); window.__t = t.id; }); return 1; })()")
        banner = "(() => { const b = document.getElementById('banner'); b.textContent = 'Нет связи с хабом — переподключаюсь'; b.classList.add('on'); return 1; })()"
        ratio = ("(() => { const cv = document.createElement('canvas').getContext('2d', {willReadFrequently: true});"
                 " const rgb = (c) => { cv.fillStyle = '#000'; cv.fillStyle = c; cv.fillRect(0, 0, 1, 1); return [...cv.getImageData(0, 0, 1, 1).data].slice(0, 3); };"
                 " const lum = (c) => c.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }).reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);"
                 " const e = document.querySelector('.ag-layer .ag-say'), a = lum(rgb(getComputedStyle(e).color)), b = lum(rgb(getComputedStyle(e.closest('.ag-layer')).backgroundColor));"
                 " return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); })()")
        self.page({"go": f"http://127.0.0.1:{self.port}/"}, {"eval": pick}, {"until": "!!window.__t"}, {"go": "about:blank"})
        got = self.opened({"eval": banner}, {"until": "!document.querySelector('.ag-layer .ag-say').hidden"},
                          {"eval": "getComputedStyle(document.documentElement).getPropertyValue('--destructive').trim()"}, {"eval": ratio})
        self.assertEqual(got[-2]["eval"], "#ef4e4e")                    # the theme is on
        self.assertGreaterEqual(got[-1]["eval"], 4.5)

    def test_space_outside_a_field_does_not_start_a_voice_message_and_the_page_has_no_errors(self):
        self.ask("r1", "Первый?")
        got = self.page({"go": f"http://127.0.0.1:{self.port}/#/s/backend"}, {"errors": 3000})
        self.assertEqual(got[-1]["errors"], [])
        # Space reaches the page's voice handler (document) only through the mode: it must not get there
        got = self.opened({"eval": "window.__space = 0, document.addEventListener('keydown', (e) => { if (e.code === 'Space') window.__space++; }), 1"},
                          {"key": " "}, {"eval": "window.__space"})
        self.assertEqual(got[-1]["eval"], 0)

    # the header entry: the button in the session header, the glyph's and edge's color against --st-wait
    HEAD = ("(() => { const b = document.querySelector('.slot-session-header .ag-open'), p = document.createElement('span');"
            " p.style.color = 'var(--st-wait)'; document.body.append(p); const wait = getComputedStyle(p).color; p.remove();"
            " if (!b) return {there: false}; const g = b.querySelector('.ag-q');"
            " return {there: true, shown: !b.hidden && b.getBoundingClientRect().width > 0, glyph: g.textContent, glyphRed: getComputedStyle(g).color === wait,"
            " edgeRed: getComputedStyle(b).borderTopColor === wait, label: b.getAttribute('aria-label'), title: b.title,"
            " fits: b.getBoundingClientRect().right <= innerWidth && document.documentElement.scrollWidth <= innerWidth,"
            " strip: document.querySelectorAll('.strip-host .ag-open').length, cards: document.querySelectorAll('main .feed .ask-card:not([hidden])').length}; })()")

    def test_the_header_button_shows_only_with_open_questions_in_the_waiting_red(self):
        url = f"http://127.0.0.1:{self.port}/#/s/backend"
        got = self.page({"go": url}, {"until": "!!document.querySelector('.slot-session-header')", "ms": 15000}, {"eval": self.HEAD})
        self.assertFalse(got[-1]["eval"].get("shown"))                  # no questions — no button
        self.ask("r1", "Сервис отвечает медленно после выката. Откатываем выпуск?")
        self.ask("r2", "Какие проверки добавить в CI?")
        got = self.page({"until": f"!!document.querySelector('{OPEN}')", "ms": 8000},
                        {"until": "document.querySelectorAll('main .feed .ask-card:not([hidden])').length === 2", "ms": 8000},
                        {"eval": self.HEAD}, self.shot("header-light.png", theme="light"), self.shot("header-dark.png", theme="dark"),
                        self.shot("header-phone-light.png", width=390, height=780, theme="light"), {"eval": self.HEAD})
        two, phone = got[2]["eval"], got[6]["eval"]
        self.assertEqual({k: two[k] for k in ("shown", "glyph", "glyphRed", "edgeRed", "label", "title", "strip", "cards")},
                         {"shown": True, "glyph": "?", "glyphRed": True, "edgeRed": True, "label": "Только вопросы: открыто 2",
                          "title": "Только вопросы: открыто 2", "strip": 0, "cards": 2})   # the page's own cards stay unfolded
        self.assertTrue(phone["shown"] and phone["fits"])
        # the questions are gone (answered in Telegram) — the button goes too
        for rid, q in (("r1", "Сервис отвечает медленно после выката. Откатываем выпуск?"), ("r2", "Какие проверки добавить в CI?")):
            self.ev("permission.answered", "backend", request_id=rid, behavior="allow", channel="telegram", owner=True, answers={q: "Да"})
        got = self.page({"until": f"!document.querySelector('{OPEN}')", "ms": 8000})
        self.assertTrue(got[0]["until"])

    def test_the_last_answer_closes_the_mode_at_once_without_waiting_for_the_session(self):
        # the session is in a turn: the answer waits in its queue, and the mode does not wait for it or show any screen
        self.ask("r1", "Первый?")
        seen = ("window.__screen = false; new MutationObserver(() => { const l = document.querySelector('.ag-layer');"
                " if (l && /Вопросов больше нет|появится здесь|Возвращаемся в хаб/.test(l.textContent)) window.__screen = true; })"
                ".observe(document.body, {subtree: true, childList: true, attributes: true, characterData: true}), 1")
        gone = ("window.__gone = null; new MutationObserver(() => { if (window.__gone == null && !document.querySelector('.ag-layer'))"
                " window.__gone = performance.now(); }).observe(document.body, {childList: true}), 1")
        got = self.opened({"eval": seen}, {"eval": gone},
                          {"eval": "window.__click = performance.now(), document.querySelector('.ag-layer .ag-slide:not([inert]) label.opt').click(), 1"},
                          {"until": f"!document.querySelector('{LAYER}')", "ms": 8000},
                          {"eval": "Math.round(window.__gone - window.__click)"},
                          {"eval": "window.__screen"}, {"eval": "document.activeElement?.id"}, {"eval": "document.getElementById('app').inert"},
                          {"eval": "[location.hash, !!history.state?.askGallery]"})
        self.assertLess(got[-5]["eval"], 5000)                           # as soon as the core took the answer
        self.assertFalse(got[-4]["eval"])                                # no "No more questions" or waiting line on the way out
        self.assertEqual(got[-3]["eval"], "msg")                         # no header button left: the session's field
        self.assertFalse(got[-2]["eval"])
        self.assertEqual(got[-1]["eval"], ["#/s/backend", False])        # as by Esc: the mode's history entry is given back
        self.taken("r1")

    def test_a_reload_in_the_mode_with_no_questions_left_closes_it_without_errors(self):
        self.ask("r1", "Первый?")
        self.page({"go": f"http://127.0.0.1:{self.port}/#/s/backend"}, {"until": f"!!document.querySelector('{OPEN}')", "ms": 15000})
        self.ev("permission.answered", "backend", request_id="r1", behavior="allow", channel="telegram", owner=True, answers={"Первый?": "Да"})
        got = self.page({"until": f"!document.querySelector('{OPEN}')", "ms": 8000},
                        {"eval": "sessionStorage.setItem('ask-gallery.open', 'backend'), history.pushState({askGallery: 'backend'}, ''), 1"},
                        {"errors": 3000},
                        {"eval": f"[!!document.querySelector('{LAYER}'), sessionStorage.getItem('ask-gallery.open'), document.getElementById('app').inert]"})
        self.assertEqual(got[2]["errors"], [])
        self.assertEqual(got[3]["eval"], [False, None, False])

    def test_a_frozen_card_keeps_the_mode_until_it_is_removed(self):
        self.ask("r1", "Как назовём очередь?")
        self.opened({"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"},
                    {"typed": "orders-retry"}, {"eval": "document.querySelector('.ag-layer').focus(), 1"})
        self.ev("permission.answered", "backend", request_id="r1", behavior="allow", channel="telegram", owner=True,
                answers={"Как назовём очередь?": "Да"})
        card = "document.querySelector('.ag-layer .ag-slide:not([inert]) .card')"
        got = self.page({"until": f"{card}?.classList.contains('frozen')", "ms": 8000},
                        {"eval": f"!!document.querySelector('{LAYER}')"})
        self.takes_answer()
        got2 = self.page({"eval": f"!!document.querySelector('{LAYER}')"},
                         {"eval": "document.querySelector('.ag-layer .frozen-bar button').click(), 1"},
                         {"until": f"!document.querySelector('{LAYER}')", "ms": 8000})
        self.assertTrue(got[1]["eval"])                                  # the typed text holds the mode
        self.assertTrue(got2[0]["eval"])                                 # also once the session took the answer

    def answered_turn(self, rid, question, answer):
        """The owner answers rid elsewhere (its own words): the core gives the session the answer as a message, the
        session takes it — a turn of its own starts. Returns the answer's seq."""
        e = self.j.append("permission.answered", "backend", {"request_id": rid, "behavior": "allow", "channel": "telegram",
                                                             "owner": True, "answers": {question: answer}})
        self.ev("turn.started", "backend", marker=f"m{e['seq']}")
        return e["seq"]

    def takes_answer(self, text="—"):
        """The session takes the latest answer (the core's message about it) and ends that turn without a question."""
        from core import journal
        seq = max(e["seq"] for e in journal.read(self.j.path) if e["type"] in ("permission.answered", "question.dismissed"))
        self.ev("turn.started", "backend", marker=f"m{seq}")
        self.end_turn(text)

    def end_turn(self, text="—"):
        self.ev("turn.result", "backend", text=text)
        self.ev("turn.stopped", "backend")

    def test_the_context_is_the_earlier_answer_and_the_text_right_before_the_card(self):
        m = self.j.append("message.received", None, {"to": "backend", "text": "Сделай очередь повторов", "channel": "web", "owner": True})
        self.ev("turn.started", "backend", marker=f"m{m['seq']}")
        self.ev("session.said", "backend", text="Работаю над очередью повторов.")
        self.ask("r1", "Как назовём очередь?")
        self.end_turn()
        self.answered_turn("r1", "Как назовём очередь?", "orders-retry")
        self.ev("session.said", "backend", text="Проверяю, свободно ли имя.")
        self.tool("backend", "t1", "grep -r orders-retry")
        self.ev("session.said", "backend", text="Принято, называю **orders-retry**.")
        self.ask("r2", "Выкатываем на стейдж сейчас?")
        got = self.opened({"until": f"{CTX}?.rows.length === 3", "ms": 8000}, {"eval": CTX},
                          self.shot("context-light.png", theme="light"))
        c = got[5]["eval"]
        self.assertIn("Как назовём очередь?", c["rows"][0])
        self.assertIn("orders-retry", c["rows"][1])
        self.assertIn("Принято, называю orders-retry.", c["rows"][2])
        self.assertFalse(any("Работаю над очередью" in r or "свободно ли" in r for r in c["rows"]))   # nor another turn, nor before a tool
        self.assertTrue(c["left"] and c["inside"] and not c["hidden"])
        self.assertEqual(c["acts"], 0)                                     # no "Reply", reactions or jumps of the feed behind
        self.assertEqual(c["md"], 1)                                       # the page's markdown

    def test_questions_in_turns_someone_else_started_show_their_own_turn_not_an_older_answer(self):
        # an answer given turns earlier belongs to another question: two questions asked in different turns after it do
        # not show it as their context, each shows the text of its own turn
        self.ask("r1", "Как назовём очередь?")
        self.end_turn()
        self.answered_turn("r1", "Как назовём очередь?", "orders-retry")
        self.ev("session.said", "backend", text="Принято, отдала исполнителю.")
        self.end_turn()
        for sender, said, rid, question in (("worker-1", "Исполнитель отчитался, разбираю его отчёт.", "r2", "Выкатываем на стейдж сейчас?"),
                                            ("worker-2", "Второй исполнитель нашёл медленный запрос.", "r3", "Добавляем индекс?")):
            m = self.j.append("message.received", None, {"to": "backend", "text": "Готово", "channel": "session", "owner": False, "sender": sender})
            self.ev("turn.started", "backend", marker=f"m{m['seq']}")
            self.ev("session.said", "backend", text=said)
            self.ask(rid, question)
            self.end_turn()
        got = self.opened({"until": f"{CTX}?.rows.length === 1", "ms": 8000}, {"eval": CTX}, {"key": "ArrowRight"},
                          {"until": f"{COUNT} === '2 из 2' && {CTX}?.rows.length === 1", "ms": 8000}, {"eval": CTX})
        first, second = got[5]["eval"]["rows"], got[-1]["eval"]["rows"]
        self.assertIn("Исполнитель отчитался, разбираю его отчёт.", first[0])
        self.assertIn("Второй исполнитель нашёл медленный запрос.", second[0])
        self.assertFalse(any("Как назовём очередь?" in r or "orders-retry" in r for r in first + second))

    def test_without_an_earlier_answer_the_context_is_the_nearest_text_of_the_turn(self):
        m = self.j.append("message.received", None, {"to": "backend", "text": "Посмотри логи", "channel": "web", "owner": True})
        self.ev("turn.started", "backend", marker=f"m{m['seq']}")
        self.ev("session.said", "backend", text="Смотрю логи сервиса после выката.")
        self.ask("r1", "Откатываем выпуск?")
        self.ev("session.said", "backend", text="Жду решения по откату.")
        got = self.opened({"until": f"{CTX}?.rows.length === 1", "ms": 8000}, {"eval": CTX})
        self.assertIn("Смотрю логи сервиса после выката.", got[5]["eval"]["rows"][0])   # the text right before the card
        # a question with no text before it: the card alone, then the turn's latest text after it, as it comes
        self.ev("turn.stopped", "backend")
        self.ev("turn.started", "backend", marker=None, prompt_head="x")
        self.tool("backend", "t1", "kubectl get pods")
        self.ask("r2", "Второй?")
        self.page({"until": f"{COUNT} === '1 из 2'", "ms": 8000}, {"key": "ArrowRight"},
                  {"until": f"{COUNT} === '2 из 2' && {CTX}?.hidden === true", "ms": 8000})
        self.ev("session.said", "backend", text="Пока жду, смотрю метрики.")
        self.page({"until": f"{CTX}?.rows.length === 1 && {CTX}.rows[0].includes('Пока жду, смотрю метрики.')", "ms": 8000})
        self.ev("session.said", "backend", text="Итог: жду решения по второму вопросу.")
        self.page({"until": f"{CTX}?.rows.length === 1 && {CTX}.rows[0].includes('Итог: жду решения')", "ms": 8000})

    def test_a_long_context_scrolls_in_its_box_and_a_phone_folds_it_above_the_card(self):
        self.ask("r1", "Как назовём очередь?")
        self.end_turn()
        self.answered_turn("r1", "Как назовём очередь?", "orders-retry")
        self.ev("session.said", "backend", text="\n\n".join(
            f"Шаг {i}: проверила конфиг очереди, миграции и права сервиса — всё сходится, иду дальше по плану выката." for i in range(12)))
        self.ask("r2", "Выкатываем на стейдж сейчас?")
        got = self.opened({"until": f"{CTX}?.rows.length === 3", "ms": 8000}, {"eval": CTX},
                          self.shot("context-long-light.png", theme="light"), self.shot("context-long-dark.png", theme="dark"),
                          {"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) .card').getBoundingClientRect().top < innerHeight / 2"})
        desk = got[5]["eval"]
        self.assertTrue(desk["scrolls"] and desk["left"] and desk["more"] is None)
        self.assertTrue(got[8]["eval"])                                   # the card is not pushed down by it
        phone = self.shot("context-phone-light.png", width=390, height=780, theme="light")
        got = self.page(phone, {"until": f"{CTX}?.above === true && {CTX}?.more === 'ещё'", "ms": 5000}, {"eval": CTX},
                        {"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) .ag-ctx-more').click(), 1"},
                        {"until": f"{CTX}?.more === 'свернуть'", "ms": 3000}, {"eval": CTX},
                        self.shot("context-phone-dark.png", width=390, height=780, theme="dark"))
        folded, opened = got[2]["eval"], got[5]["eval"]
        self.assertLessEqual(folded["h"], 100)                            # folded to a few lines
        self.assertGreater(opened["h"], folded["h"] * 3)
        self.assertTrue(folded["inside"])

    def test_the_answer_far_back_in_the_history_is_found_page_by_page(self):
        self.ask("r1", "Как назовём очередь?")
        self.end_turn()
        self.answered_turn("r1", "Как назовём очередь?", "orders-retry")
        for i in range(260):
            self.tool("backend", f"t{i}", f"echo {i}")   # a long turn: more rows than one page of the history
        self.ev("session.said", "backend", text="Всё готово к выкату.")
        self.ask("r2", "Выкатываем на стейдж сейчас?")
        got = self.opened({"until": f"{CTX}?.rows.length === 3", "ms": 15000}, {"eval": CTX})
        rows = got[5]["eval"]["rows"]
        self.assertIn("Как назовём очередь?", rows[0])
        self.assertIn("Всё готово к выкату.", rows[2])

    def test_a_question_closed_elsewhere_while_typing_keeps_the_text(self):
        self.ask("r1", "Как назовём очередь?")
        self.ask("r2", "Второй?")
        got = self.opened({"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"},
                          {"typed": "orders-retry"})
        self.ev("permission.answered", "backend", request_id="r1", behavior="allow", channel="telegram", owner=True,
                answers={"Как назовём очередь?": "Да"})
        card = "document.querySelector('.ag-layer .ag-slide:not([inert]) .card')"
        got = self.page({"until": f"{card}?.classList.contains('frozen')", "ms": 8000},
                        {"eval": f"{card}.querySelector('textarea.other').value"}, {"eval": COUNT},
                        self.shot("gallery-frozen-light.png", theme="light"),
                        {"eval": "document.querySelector('.ag-layer .frozen-bar button').click(), 1"}, {"until": f"{COUNT} === '1 из 1'", "ms": 8000}, {"eval": CUR})
        self.assertTrue(got[0]["until"])
        self.assertEqual(got[1]["eval"], "orders-retry")                # the typed text is not lost
        self.assertEqual(got[2]["eval"], "1 из 2")
        self.assertIn("Второй?", got[-1]["eval"])

    def test_back_leaves_the_mode_and_the_close_button_gives_its_history_entry_back(self):
        self.ask("r1", "Первый?")
        got = self.opened({"eval": "history.length"}, {"eval": "history.back(), 1"},
                          {"until": f"!document.querySelector('{LAYER}')"}, {"eval": "location.hash"},
                          {"eval": "document.querySelector('.ag-open').click(), 1"},
                          {"until": f"!!document.querySelector('{LAYER}')"},
                          {"eval": "document.querySelector('.ag-x').click(), 1"},
                          {"until": "!history.state?.askGallery"}, {"eval": "history.length"})
        self.assertTrue(got[6]["until"])
        self.assertEqual(got[7]["eval"], "#/s/backend")                 # Back closed the mode, not the session
        self.assertTrue(got[11]["until"])
        self.assertEqual(got[12]["eval"], got[4]["eval"])               # no stray entries pile up

    def test_a_frozen_card_outlives_esc_and_a_reopened_question_is_live_again(self):
        self.ask("r1", "Как назовём очередь?")
        self.ask("r2", "Второй?")
        self.opened({"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"},
                    {"typed": "orders-retry"})
        self.ev("permission.answered", "backend", request_id="r1", behavior="allow", channel="telegram", owner=True,
                answers={"Как назовём очередь?": "Да"})
        card = "document.querySelector('.ag-layer .ag-slide:not([inert]) .card')"
        self.page({"until": f"{card}?.classList.contains('frozen')", "ms": 8000}, {"key": "Escape"},
                  {"until": f"!document.querySelector('{LAYER}')"},
                  {"eval": "document.querySelector('.ag-open').click(), 1"},
                  {"until": f"{COUNT} === '1 из 2' && {card}?.querySelector('textarea.other').value === 'orders-retry'", "ms": 8000})
        # the session asks the same question again: the live card comes back instead of the frozen one
        self.ask("r1", "Как назовём очередь?")
        got = self.page({"until": f"{COUNT} === '1 из 2' && !{card}.classList.contains('frozen')", "ms": 8000},
                        {"eval": f"{card}.querySelector('button[type=submit], .btns .btn') !== null"})
        self.assertTrue(got[-1]["eval"])

    def test_an_own_typed_answer_leaves_without_freezing_and_space_types_in_the_field(self):
        self.ask("r1", "Как назовём очередь?")
        self.ask("r2", "Второй?")
        got = self.opened({"eval": "window.__froze = 0; new MutationObserver(() => { if (document.querySelector('.ag-layer .card.frozen')) window.__froze++; })"
                                   ".observe(document.body, {subtree: true, attributes: true, attributeFilter: ['class']}), 1"},
                          {"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"},
                          {"typed": "orders"}, {"key": " "}, {"typed": "retry"},
                          {"eval": "document.activeElement.value"}, {"key": "Enter"},
                          {"until": f"{COUNT} === '1 из 1'", "ms": 8000}, {"eval": "window.__froze"})
        self.assertEqual(got[-4]["eval"], "orders retry")                # Space is a space in the field
        self.assertEqual(got[-1]["eval"], 0)
        self.taken("r1")

    def test_the_widths_of_the_context_and_the_card_are_dragged_kept_and_reset(self):
        m = self.j.append("message.received", None, {"to": "backend", "text": "Посмотри логи", "channel": "web", "owner": True})
        self.ev("turn.started", "backend", marker=f"m{m['seq']}")
        self.ev("session.said", "backend", text="Смотрю логи сервиса после выката.")
        self.ask("r1", "Откатываем выпуск?")
        self.ask("r2", "Второй?")   # no text of the turn right before it: the card alone
        broken = """localStorage.setItem('ask-gallery.widths', '{"ctx": "wide", "card": -5}')"""   # not ours: the defaults
        got = self.opened(self.shot("widths-default.png"), {"until": f"{CTX}?.rows.length === 1", "ms": 8000}, {"eval": WID}, init=broken)
        w = got[-1]["eval"]
        self.assertEqual((w["ctx"], w["card"]), (380, 680))
        self.assertEqual((w["split"]["role"], w["split"]["tab"], w["split"]["now"]), ("separator", 0, 380))
        self.assertEqual((w["edge"]["now"], w["split"]["cursor"]), (680, "col-resize"))
        self.assertEqual(w["kept"], {"ctx": "wide", "card": -5})
        # a click with a shaky hand: the widths stay, nothing is kept over what was
        got = self.page({"eval": TO % (w["split"]["x"] + 2, w["split"]["y"] + 30)}, {"drag": SPLIT, "to": "#ag-to"}, {"eval": WID})
        self.assertEqual((got[-1]["eval"]["ctx"], got[-1]["eval"]["kept"]), (380, {"ctx": "wide", "card": -5}))
        # the divider: the context gets wider, the card narrower by as much, the pair stays where it was
        got = self.page({"eval": TO % (w["split"]["x"] + 120, w["split"]["y"])}, {"drag": SPLIT, "to": "#ag-to"}, {"eval": WID})
        d = got[-1]["eval"]
        self.assertAlmostEqual(d["ctx"], 500, delta=2)
        self.assertAlmostEqual(d["card"], 560, delta=2)
        self.assertEqual((d["left"], d["right"]), (w["left"], w["right"]))
        self.assertEqual(d["kept"], {"ctx": d["ctx"], "card": d["card"]})
        # the card's outer edge: the card grows, the pair stays in the middle (twice the move)
        got = self.page({"eval": TO % (d["edge"]["x"] + 60, d["edge"]["y"])}, {"drag": EDGE, "to": "#ag-to"}, {"eval": WID},
                        self.shot("widths-dragged.png"))
        e = got[2]["eval"]
        self.assertEqual(e["ctx"], d["ctx"])
        self.assertAlmostEqual(e["card"], d["card"] + 120, delta=3)
        self.assertEqual(e["kept"], {"ctx": e["ctx"], "card": e["card"]})
        # out of the mode and back: the same widths
        same = f"{WID}?.ctx === {e['ctx']} && {WID}.card === {e['card']}"
        self.page({"key": "Escape"}, {"until": f"!document.querySelector('{LAYER}')"},
                  {"eval": f"document.querySelector('{OPEN}').click(), 1"}, {"until": same, "ms": 8000})
        # Tab goes as the eye does: the context, the divider, the card, the card's edge
        order = ("(() => { const s = document.querySelector('.ag-layer .ag-slide:not([inert])'), all = [...s.querySelectorAll("
                 "'button, input, textarea, [tabindex]:not([tabindex=\\'-1\\'])')].filter((n) => n.getClientRects().length);"
                 " const i = (n) => all.indexOf(n), card = s.querySelector(':scope > .card');"
                 " return [i(s.querySelector('.ag-split')), Math.min(...all.filter((n) => card.contains(n)).map(i)),"
                 " Math.max(...all.filter((n) => card.contains(n)).map(i)), i(s.querySelector('.ag-edge'))]; })()")
        got = self.page({"eval": order})
        sp, first, last, ed = got[0]["eval"]
        self.assertTrue(0 <= sp < first <= last < ed, got[0]["eval"])
        # the keyboard: ←/→ on a handle change the width (Shift — a bigger step), not the question
        got = self.page({"eval": f"document.querySelector('{SPLIT}').focus(), 1"}, {"key": "ArrowRight"}, {"eval": WID}, {"eval": COUNT},
                        {"key": "ArrowLeft", "mods": ["shift"]}, {"eval": WID},
                        {"eval": f"document.querySelector('{EDGE}').focus(), 1"}, {"key": "ArrowRight"}, {"eval": WID})
        k1, k2, k3 = got[2]["eval"], got[5]["eval"], got[-1]["eval"]
        self.assertEqual((k1["ctx"], k1["card"], k1["split"]["now"]), (e["ctx"] + 16, e["card"] - 16, e["ctx"] + 16))
        self.assertEqual(got[3]["eval"], "1 из 2")
        self.assertEqual((k2["ctx"], k2["card"]), (e["ctx"] - 48, e["card"] + 48))
        self.assertEqual((k3["ctx"], k3["card"], k3["edge"]["now"]), (k2["ctx"], k2["card"] + 16, k2["card"] + 16))
        self.assertEqual(k3["kept"], {"ctx": k3["ctx"], "card": k3["card"]})
        # a narrower window: the pair fits it, neither gets under its least; wide again — the widths asked for come back
        got = self.page({"eval": f"document.querySelector('{EDGE}').blur(), 1"}, self.shot("widths-narrow-window.png", width=1000),
                        {"until": f"{WID}?.right <= innerWidth - 16 && {WID}.ctx < {k3['ctx']}", "ms": 3000}, {"eval": WID},
                        self.shot("widths-wide-again.png"), {"until": f"{WID}?.ctx === {k3['ctx']} && {WID}.card === {k3['card']}", "ms": 3000})
        n = got[3]["eval"]
        self.assertGreaterEqual(n["left"], 16)
        self.assertGreaterEqual(n["ctx"], 240)
        self.assertGreaterEqual(n["card"], 400)
        self.assertEqual(n["kept"], k3["kept"])                         # the fitting is not kept as the owner's choice
        # a double click on a handle: the default widths, nothing kept
        self.page({"eval": f"document.querySelector('{SPLIT}').dispatchEvent(new MouseEvent('dblclick', {{bubbles: true}})), 1"},
                  {"until": f"{WID}?.ctx === 380 && {WID}.card === 680 && {WID}.kept === null", "ms": 3000})
        # the card alone: no divider, its edge widens it
        got = self.page({"eval": "document.querySelector('.ag-layer').focus(), 1"}, {"key": "ArrowRight"}, {"until": f"{COUNT} === '2 из 2'"},
                        {"until": f"{WID}?.card === 680 && {WID}.ctx === null", "ms": 3000}, {"eval": WID},
                        {"eval": f"document.querySelector('{EDGE}').focus(), 1"}, {"key": "ArrowRight"}, {"eval": WID})
        self.assertIsNone(got[4]["eval"]["split"])
        self.assertEqual((got[-1]["eval"]["card"], got[-1]["eval"]["kept"]), (696, {"ctx": 380, "card": 696}))
        # the card leaves in the middle of a drag (here — a move to the other question): the drag ends, its widths are kept
        got = self.page({"eval": "document.querySelector('.ag-layer').focus(), 1"}, {"key": "ArrowLeft"}, {"until": f"{COUNT} === '1 из 2'"},
                        {"until": f"{WID}?.ctx === 380 && {ONE}", "ms": 3000}, {"eval": WID})
        s = got[-1]["eval"]
        got = self.page({"eval": TO % (s["split"]["x"] + 60, s["split"]["y"])}, {"drag": SPLIT, "to": "#ag-to", "keep": True},
                        {"eval": "document.body.classList.contains('resizing')"}, {"key": "ArrowRight"}, {"until": f"{COUNT} === '2 из 2'"},
                        {"eval": "[document.body.classList.contains('resizing'), document.querySelectorAll('.ag-grip.dragging').length]"},
                        {"drop": 1}, {"eval": WID})
        self.assertTrue(got[2]["eval"])
        self.assertEqual(got[5]["eval"], [False, 0])
        kept = got[-1]["eval"]["kept"]
        self.assertAlmostEqual(kept["ctx"], s["ctx"] + 60, delta=2)
        self.assertEqual(kept["ctx"] + kept["card"], s["ctx"] + s["card"])
        # a phone: the context above the card, no handles
        got = self.page({"touch": True}, self.shot("widths-phone.png", width=390, height=780), {"key": "ArrowLeft"},
                        {"until": f"{COUNT} === '1 из 2' && {ONE}"}, {"eval": WID})
        p = got[-1]["eval"]
        self.assertIsNone(p["split"])
        self.assertIsNone(p["edge"])
        self.assertLessEqual(p["right"], 390)

    def test_the_plugin_icon_is_the_red_question_in_a_frame_on_every_theme(self):
        # "Settings → Plugins" (and a catalog) shows the manifest icon as an <img>: the page's CSS does not reach inside it,
        # so the color is in the file itself, one red readable on the light, the dark and a theme's tile
        import xml.etree.ElementTree as ET
        os.makedirs(os.path.join(self.state, "themes"))   # an own theme of the hub (next to hub.json): a dark one, as the terminal themes
        with open(os.path.join(self.state, "themes", "phosphor.json"), "w") as f:
            json.dump({"name": "Фосфор", "dark": True, "colors": {"background": "#1e2326", "foreground": "#b8c8b0", "card": "#232a2e",
                       "muted": "#293134", "muted-foreground": "#97a598", "border": "#374145", "primary": "#83c092",
                       "destructive": "#c9906f"}}, f)
        row = "[...document.querySelectorAll('.plugin-row')].find((r) => r.querySelector('h4')?.textContent === 'ask-gallery')"
        img = f"{row}?.querySelector('.plugin-icon img')"
        # the colors the browser actually paints: every pixel of the drawn icon that is not transparent
        paint = (f"(() => {{ const i = {img}, c = document.createElement('canvas'); c.width = c.height = 48;"
                 " const x = c.getContext('2d'); x.drawImage(i, 0, 0, 48, 48); const d = x.getImageData(0, 0, 48, 48).data, out = {};"
                 " for (let k = 0; k < d.length; k += 4) if (d[k + 3] === 255) { const v = `${d[k]},${d[k + 1]},${d[k + 2]}`; out[v] = (out[v] || 0) + 1; }"
                 " return out; })()")
        plugins = ({"local": {"hub.settingsTab": "plugins"}}, {"go": "about:blank"},
                   {"go": f"http://127.0.0.1:{self.port}/#/settings"}, {"until": f"!!{row}", "ms": 8000},
                   {"eval": f"{row}.scrollIntoView({{block: 'center'}}), 1"}, {"until": f"{img}?.naturalWidth > 0"})   # a lazy <img>: loads once on the screen
        tile = {"eval": f"getComputedStyle({row}.querySelector('.plugin-icon')).backgroundColor"}   # under the icon, after a shot's theme
        n = len(plugins)
        got = self.page(*plugins,
                        {"eval": f"{img}.getAttribute('src')"},
                        {"eval": "fetch('/api/plugins/icon?name=ask-gallery').then((r) => r.text()).then((t) => { window.__svg = t; }), 1"},
                        {"until": "typeof window.__svg === 'string'"}, {"eval": "window.__svg"}, {"eval": paint},
                        self.shot("icon-settings-light.png", theme="light"), tile, self.shot("icon-settings-dark.png", theme="dark"), tile,
                        {"local": {"hub.settingsTab": "theme"}}, {"go": "about:blank"}, {"go": f"http://127.0.0.1:{self.port}/#/settings"},
                        {"until": "[...document.querySelectorAll('button')].some((b) => b.textContent.includes('Фосфор'))", "ms": 8000},
                        {"eval": "[...document.querySelectorAll('button')].find((b) => b.textContent.includes('Фосфор')).click(), 1"},
                        {"until": "getComputedStyle(document.documentElement).getPropertyValue('--background').trim() === '#1e2326'"},
                        *plugins, self.shot("icon-settings-phosphor.png", theme="dark"), tile)
        self.assertTrue(got[n]["eval"].startswith("/api/plugins/icon?name=ask-gallery"), got[n]["eval"])
        svg = ET.fromstring(got[n + 3]["eval"])
        self.assertEqual(svg.get("viewBox"), "0 0 48 48")
        shapes = [e for e in svg.iter() if e.tag.rsplit("}", 1)[-1] in ("rect", "path")]
        self.assertEqual([e.tag.rsplit("}", 1)[-1] for e in shapes], ["rect", "path"])     # the frame and the question mark
        for e in shapes:   # every shape has its own color: no fill left to the default black
            self.assertEqual(e.get("stroke"), "#e5484d")
            self.assertIn(e.get("fill"), ("none", "#e5484d"))
        drawn = got[n + 4]["eval"]
        self.assertGreater(sum(drawn.values()), 150)                   # the frame and the glyph are there, not a blank
        for rgb in drawn:   # opaque pixels are the red alone (the browser's color management may move a channel by one)
            self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(map(int, rgb.split(",")), (229, 72, 77))), rgb)
        # the red reads on the tile of each theme: light, dark and the own dark one (3:1, a graphical object)
        def lum(rgb):   # relative luminance (WCAG)
            return sum(w * (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
                       for w, c in zip((0.2126, 0.7152, 0.0722), (v / 255 for v in rgb)))
        tiles = [got[n + 6]["eval"], got[n + 8]["eval"], got[-1]["eval"]]
        self.assertEqual(len(set(tiles)), 3, tiles)                    # three different tiles were measured
        for bg in tiles:
            a, b = sorted((lum((229, 72, 77)), lum(map(float, bg[bg.index("(") + 1:bg.index(")")].split(",")[:3]))))
            self.assertGreaterEqual((b + 0.05) / (a + 0.05), 3, bg)

    # ---- every session's questions ----

    # the sessions bar over the stage: each chip's session, its number of questions and whether it is the shown one; the
    # header's session
    BAR = ("(() => { const b = document.querySelector('.ag-layer .ag-bar'); if (!b) return null;"
           " return {shown: !b.hidden && b.getClientRects().length > 0, who: document.querySelector('.ag-layer .ag-who').textContent.trim(),"
           " chips: [...b.querySelectorAll('.ag-chip')].map((c) => [c.dataset.session, +c.querySelector('.n').textContent,"
           " c.getAttribute('aria-current') === 'true'])}; })()")
    ALL = "#slot-sidebar-header .ag-all"
    WHO = "document.querySelector('.ag-layer .ag-who')?.textContent.trim()"

    def three(self):
        """Questions of three sessions: backend's two asked first, then infra's one, then frontend's two — the order of
        "Waiting for you" in the list (the oldest question first), not the order the sessions were made in."""
        self.session("frontend", "🎨")
        self.session("infra", "🧱")
        t = time.time() - 100
        self.ask("b1", "Бэкенд: первый?", ts=t)
        self.ask("b2", "Бэкенд: второй?", ts=t + 1)
        self.ask("i1", "Инфра: единственный?", who="infra", ts=t + 2)
        self.ask("f1", "Фронт: первый?", who="frontend", ts=t + 3)
        self.ask("f2", "Фронт: второй?", who="frontend", ts=t + 4)

    def test_every_sessions_questions_are_grouped_by_session_and_arrows_cross_between_them(self):
        self.three()
        got = self.opened({"until": f"{self.BAR}?.chips.length === 3"}, {"eval": self.BAR}, {"eval": COUNT}, {"eval": CUR},
                          self.shot("all-light.png", theme="light"), self.shot("all-dark.png", theme="dark"))
        bar = got[5]["eval"]
        self.assertTrue(bar["shown"])
        self.assertEqual(bar["chips"], [["backend", 2, True], ["infra", 1, False], ["frontend", 2, False]])
        self.assertEqual(bar["who"], "🛠️ backend")
        self.assertEqual(got[6]["eval"], "1 из 5")                        # one list: every session's questions
        self.assertIn("Бэкенд: первый?", got[7]["eval"])
        # → at the end of a session's questions: the next session's first one, the header and the shown chip go with it
        got = self.page({"key": "ArrowRight"}, {"until": f"{COUNT} === '2 из 5' && {ONE}"},
                        {"key": "ArrowRight"}, {"until": f"{COUNT} === '3 из 5' && {ONE}"}, {"eval": CUR}, {"eval": self.BAR},
                        {"key": "ArrowLeft"}, {"until": f"{COUNT} === '2 из 5' && {ONE}"}, {"eval": CUR}, {"eval": self.BAR})
        self.assertIn("Инфра: единственный?", got[4]["eval"])
        self.assertEqual((got[5]["eval"]["who"], [c[2] for c in got[5]["eval"]["chips"]]), ("🧱 infra", [False, True, False]))
        self.assertIn("Бэкенд: второй?", got[8]["eval"])                  # ← back over the edge: the previous session's last
        self.assertEqual(got[9]["eval"]["who"], "🛠️ backend")
        # ↓/↑ — the next and the previous session's first question; a chip — its session's first question
        got = self.page({"key": "ArrowDown"}, {"until": f"{COUNT} === '3 из 5' && {ONE}"}, {"key": "ArrowDown"},
                        {"until": f"{COUNT} === '4 из 5' && {ONE}"}, {"eval": CUR}, {"key": "ArrowDown"}, {"eval": COUNT},
                        {"key": "ArrowUp"}, {"until": f"{COUNT} === '3 из 5' && {ONE}"},
                        {"eval": "document.querySelector('.ag-layer .ag-chip[data-session=backend]').click(), 1"},
                        {"until": f"{COUNT} === '1 из 5' && {ONE}"}, {"eval": self.BAR})
        self.assertIn("Фронт: первый?", got[4]["eval"])
        self.assertEqual(got[6]["eval"], "4 из 5")                        # the last session: nowhere further down
        self.assertEqual([c[2] for c in got[-1]["eval"]["chips"]], [True, False, False])

    def test_the_last_answer_of_a_session_brings_the_next_sessions_first_and_each_answer_goes_to_its_session(self):
        self.three()
        pick = "document.querySelector('.ag-layer .ag-slide:not([inert]) label.opt').click(), 1"
        got = self.opened({"until": f"{self.BAR}?.chips.length === 3"}, {"key": "ArrowRight"}, {"until": f"{COUNT} === '2 из 5' && {ONE}"},
                          {"eval": pick}, {"eval": self.MID}, {"eval": self.PLAY},
                          {"until": f"{CUR}?.includes('Бэкенд: первый?') && {ONE}", "ms": 8000}, {"eval": COUNT}, {"eval": self.BAR})
        # the last of backend's left answered while one of its own waits before it: the session's questions go on first
        out, inn = self.mid(got[8]["eval"])
        self.assertLess(out["y"], -50)
        self.assertLess(inn["x"], -100)                                   # from the left: it was before it
        self.assertEqual(got[11]["eval"], "1 из 4")
        self.assertEqual(got[12]["eval"]["chips"][0], ["backend", 1, True])
        self.taken("b2")
        # backend's last one: it flies up, infra's first comes in from the right, the header changes with it
        got = self.page({"eval": pick}, {"eval": self.MID}, {"eval": self.WHO}, {"eval": self.PLAY},
                        {"until": f"{CUR}?.includes('Инфра: единственный?') && {ONE}", "ms": 8000}, {"eval": COUNT}, {"eval": self.BAR})
        out, inn = self.mid(got[1]["eval"])
        self.assertLess(out["y"], -50)
        self.assertGreater(inn["x"], 100)
        self.assertEqual(got[2]["eval"], "🧱 infra")                       # already while the slide comes in
        self.assertEqual(got[5]["eval"], "1 из 3")
        self.assertEqual(got[6]["eval"]["chips"], [["infra", 1, True], ["frontend", 2, False]])
        self.taken("b1")
        self.assertEqual(self.pending("infra"), ["i1"])                   # nothing went to another session
        self.assertEqual(self.pending("frontend"), ["f1", "f2"])
        # infra's answer goes to infra; then frontend's two; the last one closes the mode
        got = self.page({"eval": pick}, {"until": f"{CUR}?.includes('Фронт: первый?') && {ONE}", "ms": 8000}, {"eval": self.BAR})
        self.assertEqual(got[-1]["eval"]["chips"], [["frontend", 2, True]])   # one session left: the row stays, the stage does not jump
        self.assertTrue(got[-1]["eval"]["shown"])
        self.taken("i1", who="infra")
        self.assertEqual(self.pending("frontend"), ["f1", "f2"])
        self.page({"eval": pick}, {"until": f"{CUR}?.includes('Фронт: второй?') && {ONE}", "ms": 8000},
                  {"eval": pick}, {"until": f"!document.querySelector('{LAYER}')", "ms": 8000})
        self.taken("f1", "f2", who="frontend")
        self.assertEqual(self.pending(), [])

    def test_a_new_question_of_another_session_joins_its_group_without_moving_the_shown_card(self):
        self.three()
        got = self.opened({"until": f"{self.BAR}?.chips.length === 3"}, {"key": "ArrowRight"}, {"key": "ArrowRight"},
                          {"until": f"{COUNT} === '3 из 5' && {ONE} && {CUR}?.includes('Инфра')"})
        self.session("search", "🔎")
        self.ask("s1", "Поиск: новый?", who="search")
        self.ask("b3", "Бэкенд: третий?")
        got = self.page({"until": f"{self.BAR}?.chips.length === 4 && {COUNT} === '4 из 7'", "ms": 8000},
                        {"eval": self.BAR}, {"eval": CUR}, {"eval": "document.querySelectorAll('.ag-layer .ag-slide').length"})
        self.assertEqual(got[1]["eval"]["chips"], [["backend", 3, False], ["infra", 1, True], ["frontend", 2, False], ["search", 1, False]])
        self.assertIn("Инфра: единственный?", got[2]["eval"])            # the shown card stays where it was
        self.assertEqual(got[3]["eval"], 1)                                # no move started
        got = self.page({"key": "ArrowUp"}, {"until": f"{COUNT} === '1 из 7' && {ONE}"}, {"key": "ArrowRight"}, {"key": "ArrowRight"},
                        {"until": f"{COUNT} === '3 из 7' && {ONE}"}, {"eval": CUR})
        self.assertIn("Бэкенд: третий?", got[-1]["eval"])                # at the end of its session's group

    def test_the_header_button_starts_with_its_session_and_goes_on_to_the_others(self):
        self.three()
        go = {"go": f"http://127.0.0.1:{self.port}/#/s/frontend"}
        got = self.page(go, {"until": f"!!document.querySelector('{OPEN}')", "ms": 15000},
                        {"eval": f"document.querySelector('{OPEN}').getAttribute('aria-label')"},
                        {"eval": f"document.querySelector('{OPEN}').click(), 1"},
                        {"until": f"{self.BAR}?.chips.length === 3"}, {"eval": self.BAR}, {"eval": CUR})
        self.assertEqual(got[2]["eval"], "Только вопросы: открыто 2")    # the header counts its own session's
        self.assertEqual(got[5]["eval"]["chips"], [["frontend", 2, True], ["backend", 2, False], ["infra", 1, False]])
        self.assertIn("Фронт: первый?", got[6]["eval"])

    # the entry in the sidebar's search row: shown, its number and label, in the search row next to the "Waiting" pill
    ENTRY = ("(() => { const b = document.querySelector('#slot-sidebar-header .ag-all'); if (!b) return {there: false};"
             " const r = b.getBoundingClientRect(), row = b.closest('.search-row') || b.parentElement.parentElement, p = document.getElementById('wpill');"
             " return {there: true, shown: !b.hidden && r.width > 0, n: b.querySelector('.ag-n').textContent, label: b.getAttribute('aria-label'),"
             " h: Math.round(r.height), pillH: p && !p.hidden ? Math.round(p.getBoundingClientRect().height) : null,"
             " inRow: r.top >= row.getBoundingClientRect().top - 1 && r.bottom <= row.getBoundingClientRect().bottom + 1,"
             " fits: r.right <= innerWidth}; })()")

    def test_the_sidebar_entry_shows_every_sessions_questions_and_opens_the_mode_from_the_first(self):
        self.session("frontend", "🎨")
        got = self.page({"go": f"http://127.0.0.1:{self.port}/#/s/frontend"}, {"until": "!!document.getElementById('slot-sidebar-header')", "ms": 15000},
                        {"until": "!!document.querySelector('.slot-session-header')", "ms": 15000}, {"eval": self.ENTRY})
        self.assertFalse(got[-1]["eval"].get("shown"))                   # no questions — no entry
        self.ask("b1", "Бэкенд: первый?", ts=time.time() - 10)
        self.ask("f1", "Фронт: первый?", who="frontend")
        got = self.page({"until": f"!!document.querySelector('{self.ALL}:not([hidden])')", "ms": 8000},
                        {"until": f"document.querySelector('{self.ALL} .ag-n').textContent === '2'", "ms": 8000}, {"eval": self.ENTRY},
                        self.shot("entry-light.png", theme="light"), self.shot("entry-dark.png", theme="dark"))
        e = got[2]["eval"]
        self.assertEqual((e["shown"], e["n"], e["label"]), (True, "2", "Только вопросы всех сессий: открыто 2"))
        self.assertTrue(e["inRow"] and e["fits"])
        self.assertEqual(e["h"], e["pillH"])                              # as tall as the "Waiting for you" pill next to it
        # from the frontend session's page, the sidebar entry starts at the list's first session, not the open one
        got = self.page({"eval": f"document.querySelector('{self.ALL}').click(), 1"}, {"until": f"{self.BAR}?.chips.length === 2"},
                        {"eval": self.BAR}, {"eval": CUR}, {"eval": "history.state?.askGallery"},
                        {"eval": "location.reload(), 1"}, {"until": f"{self.BAR}?.chips.length === 2 && {COUNT} === '1 из 2'", "ms": 15000})
        self.assertEqual(got[2]["eval"]["chips"], [["backend", 1, True], ["frontend", 1, False]])
        self.assertIn("Бэкенд: первый?", got[3]["eval"])
        self.assertEqual(got[4]["eval"], "*")
        # answered elsewhere: the number goes down; none left — the entry goes too
        got = self.page({"key": "Escape"}, {"until": f"!document.querySelector('{LAYER}')"})
        self.ev("permission.answered", "backend", request_id="b1", behavior="allow", channel="telegram", owner=True, answers={"Бэкенд: первый?": "Да"})
        self.page({"until": f"document.querySelector('{self.ALL} .ag-n').textContent === '1'", "ms": 8000})
        self.ev("permission.answered", "frontend", request_id="f1", behavior="allow", channel="telegram", owner=True, answers={"Фронт: первый?": "Да"})
        self.page({"until": f"!document.querySelector('{self.ALL}:not([hidden])')", "ms": 8000})

    def test_many_sessions_wrap_on_a_wide_screen_so_every_chip_is_in_reach_of_the_mouse(self):
        t = time.time() - 100
        for i in range(12):
            self.session(f"worker-{i:02d}", "🛠️")
            self.ask(f"w{i}", f"Вопрос {i}?", who=f"worker-{i:02d}", ts=t + i)
        seen = ("(() => { const b = document.querySelector('.ag-layer .ag-bar'), r = b.getBoundingClientRect();"
                " return [...b.querySelectorAll('.ag-chip')].every((c) => { const x = c.getBoundingClientRect();"
                " return x.left >= r.left && x.right <= r.right && x.bottom <= r.bottom; }); })()")
        got = self.opened({"until": f"{self.BAR}?.chips.length === 12"}, {"eval": seen}, self.shot("all-many-light.png", theme="light"), at="worker-00")
        self.assertTrue(got[5]["eval"])

    def test_the_switcher_on_a_phone_scrolls_sideways_and_keeps_the_page_width(self):
        self.three()
        self.session("search-and-indexing-service", "🔎")
        self.ask("s1", "Поиск: новый?", who="search-and-indexing-service")
        fit = ("(() => { const b = document.querySelector('.ag-layer .ag-bar'), c = b.querySelector('[aria-current=true]').getBoundingClientRect();"
               " return {page: document.documentElement.scrollWidth <= innerWidth, bar: b.scrollWidth > b.clientWidth,"
               " cur: c.left >= 0 && c.right <= innerWidth, h: Math.round(c.height)}; })()")
        got = self.opened({"touch": True}, self.shot("all-phone-light.png", width=390, height=780, theme="light"),
                          {"until": f"{self.BAR}?.chips.length === 4"}, {"eval": fit},
                          {"eval": "document.querySelector('.ag-layer .ag-chip[data-session=search-and-indexing-service]').click(), 1"},
                          {"until": f"{COUNT} === '6 из 6' && {ONE}"}, {"eval": fit},
                          self.shot("all-phone-dark.png", width=390, height=780, theme="dark"))
        first, last = got[7]["eval"], got[10]["eval"]
        self.assertTrue(first["page"] and first["bar"] and first["cur"])
        self.assertGreaterEqual(first["h"], 40)                            # a finger's target
        self.assertTrue(last["page"] and last["cur"])                      # the far chip scrolled into sight

    def test_up_and_down_inside_a_card_scroll_it_and_leave_the_session_alone(self):
        self.session("infra", "🧱")
        self.ask("b1", *[f"Бэкенд: вопрос {i}?" for i in range(6)], multi=True, ts=time.time() - 10)
        self.ask("i1", "Инфра: единственный?", who="infra")
        stage = "document.querySelector('.ag-layer .ag-stage')"
        got = self.opened({"until": f"{self.BAR}?.chips.length === 2"},
                          {"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) input[type=checkbox]').focus(), 1"},
                          {"eval": f"{stage}.scrollTop"}, {"key": "ArrowDown"}, {"key": "ArrowDown"},
                          {"until": f"{stage}.scrollTop > 0"}, {"eval": COUNT},
                          {"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"},
                          {"key": "ArrowDown"}, {"eval": COUNT},
                          {"eval": "document.querySelector('.ag-layer').focus(), 1"}, {"key": "ArrowDown"},
                          {"until": f"{COUNT} === '2 из 2' && {ONE}"}, {"eval": CUR})
        self.assertEqual(got[6]["eval"], 0)
        self.assertEqual(got[10]["eval"], "1 из 2")                      # a checkbox: the card scrolled, the session stayed
        self.assertEqual(got[13]["eval"], "1 из 2")                      # a text field: its own arrows
        self.assertIn("Инфра: единственный?", got[-1]["eval"])           # outside the card: the next session

    def hub_with_a_shown_question(self):
        """The hub with a question of its own asked last, two sessions, and the hub showing session b's question in its
        chat (hub question show): the same question in b's pending and in the hub's shown."""
        from core import journal, reducer
        self.ev("session.requested", "hub", session_id="s-h", cwd="/h", kind="hub", channel="cli", owner=True)
        self.ev("session.started", "hub", session_id="s-h")
        self.ev("turn.started", "hub", marker=None, prompt_head="x")
        self.session("a", "🅰️")
        self.session("b", "🅱️")
        t = time.time() - 100
        self.ask("ra", "Вопрос a?", who="a", ts=t)
        self.ask("rb", "Вопрос b?", who="b", ts=t + 1)
        self.ask("rh", "Вопрос хаба?", who="hub", ts=t + 2)
        st = reducer.fold(reducer.empty(), journal.read(self.j.path))
        qid = st["sessions"]["b"]["asks"][0]["id"]
        self.ev("question.shown", "b", id=qid, channel="session", owner=False, sender="hub")

    def test_the_hub_goes_first_and_a_question_it_shows_in_its_chat_comes_once_in_its_askers_group(self):
        self.hub_with_a_shown_question()
        pick = "document.querySelector('.ag-layer .ag-slide:not([inert]) label.opt').click(), 1"
        got = self.page({"go": f"http://127.0.0.1:{self.port}/#/s/hub"},
                        {"until": f"document.querySelector('{OPEN}')?.getAttribute('aria-label') === 'Только вопросы: открыто 2'", "ms": 15000},
                        {"until": f"!!document.querySelector('{self.ALL}:not([hidden])')"}, {"eval": f"document.querySelector('{self.ALL} .ag-n').textContent"},
                        {"eval": f"document.querySelector('{self.ALL}').click(), 1"}, {"until": f"{self.BAR}?.chips.length === 3"},
                        {"eval": self.BAR}, {"eval": COUNT}, {"eval": CUR})
        self.assertEqual(got[3]["eval"], "3")                             # no copy of b's question
        self.assertEqual([c[:2] for c in got[6]["eval"]["chips"]], [["hub", 1], ["a", 1], ["b", 1]])
        self.assertEqual(got[7]["eval"], "1 из 3")
        self.assertIn("Вопрос хаба?", got[8]["eval"])
        # the hub's own answered: its header button counts the shown one; opened from it — b's question first, then a's
        got = self.page({"eval": pick}, {"until": f"{CUR}?.includes('Вопрос a?') && {ONE}", "ms": 8000}, {"key": "Escape"},
                        {"until": f"!document.querySelector('{LAYER}')"},
                        {"until": f"document.querySelector('{OPEN}')?.getAttribute('aria-label') === 'Только вопросы: открыто 1'", "ms": 8000},
                        {"eval": f"document.querySelector('{OPEN}').click(), 1"}, {"until": f"{self.BAR}?.chips.length === 2"},
                        {"eval": self.BAR}, {"eval": CUR})
        self.assertEqual([c[:2] for c in got[7]["eval"]["chips"]], [["b", 1], ["a", 1]])
        self.assertIn("Вопрос b?", got[8]["eval"])
        self.taken("rh", who="hub")
        # the answer to the shown question goes to b, its asker
        self.page({"eval": pick}, {"until": f"{CUR}?.includes('Вопрос a?') && {ONE}", "ms": 8000})
        self.taken("rb", who="b")
        self.assertEqual(self.pending("a"), ["ra"])
