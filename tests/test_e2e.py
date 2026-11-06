"""«Только вопросы» в настоящем браузере: страница хаба на временном журнале, плагин из этой папки, ответы идут
через настоящую свёртку ядра (core_decides). Живой хаб не трогается.

Запуск — из рабочей копии agents-hub-core (там tests/ и modules/):
  cd <agents-hub-core> && python3.12 -m unittest discover -s <ask-gallery>/tests -t <ask-gallery>/tests
Скриншоты — в папку HUB_TEST_ASK_SHOTS, если она задана."""
import os
import sys

sys.path.insert(0, os.getcwd())   # the hub repo: tests/ and core/ come from there
import tests  # noqa: E402,F401 — drops the machine's own HUB_* settings
import json  # noqa: E402
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
# the mode's own 1-second timer of "No more questions" (set right from the plugin's file, not page code it calls; keep
# 1000 equal to LEAVE in main.js): window.__leaves — how many were started, __cancelled — how many were cancelled;
# __hold — it waits a minute instead (the screen stays for the test's steps)
TIMERS = ("const st = window.setTimeout, ct = window.clearTimeout, own = new Set(); window.__leaves = 0; window.__cancelled = 0;"
          " window.setTimeout = (f, ms, ...a) => { if (ms !== 1000 || !String(new Error().stack).split('\\n')[2]?.includes('ask-gallery/web/main.js')) return st(f, ms, ...a);"
          " window.__leaves++; const id = st(f, window.__hold ? 60000 : ms, ...a); own.add(id); return id; };"
          " window.clearTimeout = (id) => { if (own.delete(id)) window.__cancelled++; return ct(id); };")
HOLD = TIMERS + " window.__hold = true;"
# when "No more questions" showed and when the mode left (performance.now)
WATCH = ("window.__shown = window.__gone = window.__leaving = null; new MutationObserver(() => { const e = document.querySelector('.ag-layer .ag-empty');"
         " if (e && !e.hidden && window.__shown == null) window.__shown = performance.now();"
         " const h = document.querySelector('.ag-layer .ag-empty .hint'); if (h && !h.closest('[hidden]') && h.textContent === 'Возвращаемся в хаб.' && window.__leaving == null) window.__leaving = performance.now();"
         " if (!document.querySelector('.ag-layer') && window.__gone == null) window.__gone = performance.now(); })"
         ".observe(document.body, {subtree: true, childList: true, attributes: true}), 1")
# the context next to the shown card: its rows' text, whether it is visible, where it stands against the card
CTX = ("(() => { const s = document.querySelector('.ag-layer .ag-slide:not([inert])'), c = s?.querySelector('.ag-ctx'); if (!c) return null;"
       " const card = s.querySelector(':scope > .card').getBoundingClientRect(), x = c.getBoundingClientRect(), b = c.querySelector('.ag-ctx-body');"
       " return {hidden: c.hidden, rows: [...b.children].map((r) => (r.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 90)),"
       " left: x.right <= card.left, above: x.bottom <= card.top, inside: x.left >= 0 && x.right <= innerWidth,"
       " scrolls: b.scrollHeight > b.clientHeight + 1 && getComputedStyle(b).overflowY === 'auto', h: Math.round(b.clientHeight),"
       " more: (() => { const m = c.querySelector('.ag-ctx-more'); return m && !m.hidden && getComputedStyle(m).display !== 'none' ? m.textContent : null; })(),"
       " acts: c.querySelectorAll('.reply-btn, .react-add, .quote-jump[role]').length, md: c.querySelectorAll('strong').length}; })()")
OPEN = ".slot-session-header .ag-open:not([hidden])"
LAYER = ".ag-layer"
COUNT = "document.querySelector('.ag-layer .ag-count')?.textContent"
CUR = "document.querySelector('.ag-layer .ag-slide:not([inert]) legend')?.textContent"


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
        self.ev("session.requested", "shop", session_id="s-b", cwd="/w", channel="cli", owner=True, icon="🛠️")
        self.ev("session.started", "shop", session_id="s-b")
        self.ev("turn.started", "shop", marker=None, prompt_head="x")

    def ask(self, rid, *questions, multi=False):
        self.ev("permission.requested", "shop", request_id=rid, tool="AskUserQuestion", interactive=True, input={
            "questions": [{"question": q, "multiSelect": multi, "header": "Выбор",
                           "options": [{"label": "Да", "description": "Делаем сейчас"}, {"label": "Нет"},
                                       {"label": "Позже", "description": "Вернёмся на следующей неделе"}]}
                          for q in questions]})

    def page(self, *steps):
        # cdp.mjs returns the last value of an "until" that timed out: here every wait must come true
        got = super().page(*steps)
        for step, out in zip(steps, got):
            if "until" in step:
                self.assertTrue(out["until"], f"не дождался: {step['until']}")
        return got

    def shot(self, name, **kw):
        return {"shot": os.path.join(self.shots, name), "width": 1300, "height": 860, **kw}

    def opened(self, *more, init=None):
        go = {"go": f"http://127.0.0.1:{self.port}/#/s/shop", **({"init": init} if init else {})}
        return self.page(go, {"until": f"!!document.querySelector('{OPEN}')", "ms": 15000},
                         {"eval": f"document.querySelector('{OPEN}').click(), 1"},
                         {"until": f"!!document.querySelector('{LAYER} .ag-slide')"}, *more)

    def pending(self):
        from core import journal, reducer   # the core's own fold of the test journal
        st = reducer.fold(reducer.empty(), journal.read(self.j.path))
        s = st["sessions"]["shop"]   # a question form is an ask of the session; a tool permission — its pending
        return [r["request_id"] for r in (s.get("asks") or []) + (s.get("pending") or [])]

    def test_the_gallery_moves_answers_and_waits_while_the_session_works_on_them(self):
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
                          {"eval": "document.querySelector('.ag-prev').disabled"}, init=FREEZE + HOLD)
        self.assertEqual(got[4]["eval"], "1 из 3")
        self.assertEqual(got[5]["eval"], 3)                            # the page's feed keeps its cards: nothing is folded
        self.assertEqual(got[6]["eval"].strip(), "🛠️ shop")
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
        self.assertNotIn("r1", self.pending())                          # the core took the answer
        # several options and "Answer"; then a question arrives while the mode is open — it joins the end
        got = self.page({"eval": "(() => { const s = document.querySelector('.ag-layer .ag-slide:not([inert])');"
                                 " const b = s.querySelectorAll('input[type=checkbox]'); b[0].click(); b[2].click();"
                                 " s.querySelector('button[type=submit]').click(); return 1; })()"},
                        {"until": f"{COUNT} === '1 из 1'", "ms": 8000})
        self.assertTrue(got[-1]["until"])
        self.assertNotIn("r2", self.pending())
        self.ask("r4", "Переносим окно работ на субботу?")
        got = self.page({"until": f"{COUNT} === '1 из 2'", "ms": 8000}, {"eval": CUR})
        self.assertIn("Как назовём", got[-1]["eval"])                   # the shown card stays; the new one is second
        # a custom answer (Enter), then × on the last one — closed without an answer, it leaves too
        got = self.page({"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"},
                        {"typed": "orders-retry"}, {"key": "Enter"},
                        {"until": f"{COUNT} === '1 из 1'", "ms": 8000}, {"eval": CUR},
                        {"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) .card-x').click(), 1"},
                        {"until": "!document.querySelector('.ag-layer .ag-empty').hidden", "ms": 8000},
                        {"until": "document.activeElement?.classList.contains('ag-home')"},
                        self.shot("gallery-empty-light.png", theme="light"),
                        {"eval": "document.querySelector('.ag-empty .hint').textContent"},
                        {"eval": "document.querySelector('.ag-layer .ag-nav').hidden"},
                        {"eval": "(() => { const e = document.querySelector('.ag-empty').getBoundingClientRect(),"
                                 " t = document.querySelector('.ag-top').getBoundingClientRect();"
                                 " return t.width === innerWidth && Math.abs(e.left + e.width / 2 - innerWidth / 2) < 2; })()"})
        self.assertIn("Переносим окно", got[4]["eval"])
        self.assertTrue(got[7]["until"])                                # the focus waits on "Go to the hub"
        self.assertEqual(got[9]["eval"], "Ваш ответ ждёт своей очереди у сессии — новый вопрос появится здесь.")   # the answers wait in its queue
        self.assertTrue(got[-2]["eval"])
        self.assertTrue(got[-1]["eval"])                                # one column: the header across, the empty screen centred
        self.assertEqual(self.pending(), [])
        # the session asks again while it works on the answers: the question slides in; Esc leaves the mode and does not
        # close the question
        self.ask("r5", "Включаем новый кэш для всех?")
        got = self.page({"until": f"{COUNT} === '1 из 1'", "ms": 8000},
                        {"key": "Escape"}, {"until": f"!document.querySelector('{LAYER}')"},
                        {"eval": "document.getElementById('app').inert"},
                        {"eval": "document.activeElement?.classList.contains('ag-open')"})
        self.assertTrue(got[2]["until"])
        self.assertFalse(got[3]["eval"])
        self.assertTrue(got[4]["eval"])                                 # the focus is back on the header button
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
                        {"until": f"{COUNT} === '1 из 1'", "ms": 8000}, {"eval": "window.__moves"})
        self.assertEqual(got[-1]["eval"], [False, False])

    def test_keys_swap_cards_at_once_and_buttons_slide(self):
        self.ask("r1", "Первый?")
        self.ask("r2", "Второй?")
        got = self.opened({"eval": "window.__n = () => document.querySelector('.ag-stage').getAnimations({subtree: true}).length, 1"},
                          {"key": "ArrowRight"}, {"until": f"{COUNT} === '2 из 2'"}, {"eval": "window.__n()"},
                          {"eval": "document.querySelector('.ag-prev').click(), window.__n()"})
        self.assertEqual(got[-2]["eval"], 0)
        self.assertEqual(got[-1]["eval"], 2)

    def test_space_outside_a_field_does_not_start_a_voice_message_and_the_page_has_no_errors(self):
        self.ask("r1", "Первый?")
        got = self.page({"go": f"http://127.0.0.1:{self.port}/#/s/shop"}, {"errors": 3000})
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
        url = f"http://127.0.0.1:{self.port}/#/s/shop"
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
            self.ev("permission.answered", "shop", request_id=rid, behavior="allow", channel="telegram", owner=True, answers={q: "Да"})
        got = self.page({"until": f"!document.querySelector('{OPEN}')", "ms": 8000})
        self.assertTrue(got[0]["until"])

    def test_the_last_answer_shows_no_more_questions_for_a_second_and_the_mode_leaves_by_itself(self):
        self.ask("r1", "Первый?")
        self.opened({"eval": WATCH}, {"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) label.opt').click(), 1"},
                    {"until": "!document.querySelector('.ag-layer .ag-empty').hidden", "ms": 8000})
        self.takes_answer()
        got = self.page({"until": f"!document.querySelector('{LAYER}')", "ms": 10000},
                          {"eval": "[Math.round(window.__gone - window.__shown), Math.round(window.__gone - window.__leaving)]"},
                          {"eval": "document.activeElement?.id"}, {"eval": "document.getElementById('app').inert"},
                          {"eval": "[location.hash, !!history.state?.askGallery]"})
        shown, leaving = got[1]["eval"]
        self.assertGreaterEqual(shown, 950)                               # "No more questions" was on screen (while the session took the answer, too)
        self.assertGreaterEqual(leaving, 950)                             # ~1 s after "Going back to the hub."
        self.assertLess(leaving, 2500)
        self.assertEqual(got[2]["eval"], "msg")                          # no header button left: the session's field
        self.assertFalse(got[3]["eval"])
        self.assertEqual(got[4]["eval"], ["#/s/shop", False])        # as by Esc: the mode's history entry is given back
        self.assertNotIn("r1", self.pending())

    def test_a_new_question_within_the_second_cancels_the_way_back(self):
        self.ask("r1", "Первый?")
        self.opened({"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) label.opt').click(), 1"},
                    {"until": "!document.querySelector('.ag-layer .ag-empty').hidden", "ms": 8000}, init=HOLD)
        self.takes_answer()
        got = self.page({"until": "window.__leaves >= 1 && document.querySelector('.ag-empty .hint').textContent === 'Возвращаемся в хаб.'", "ms": 8000},
                        {"eval": "window.__c0 = window.__cancelled, 1"})
        self.ask("r2", "Второй?")
        got = self.page({"until": f"{COUNT} === '1 из 1' && window.__cancelled > window.__c0", "ms": 8000},
                        {"eval": f"[!!document.querySelector('{LAYER}'), document.querySelector('.ag-layer .ag-empty').hidden]"})
        self.assertEqual(got[1]["eval"], [True, True])

    def test_a_frozen_card_keeps_the_mode_until_it_is_removed(self):
        self.ask("r1", "Как назовём очередь?")
        self.opened({"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"},
                    {"typed": "orders-retry"}, {"eval": "document.querySelector('.ag-layer').focus(), 1"}, init=TIMERS)
        self.ev("permission.answered", "shop", request_id="r1", behavior="allow", channel="telegram", owner=True,
                answers={"Как назовём очередь?": "Да"})
        card = "document.querySelector('.ag-layer .ag-slide:not([inert]) .card')"
        got = self.page({"until": f"{card}?.classList.contains('frozen')", "ms": 8000},
                        {"eval": f"[!!document.querySelector('{LAYER}'), window.__leaves, document.querySelector('.ag-layer .ag-empty').hidden]"})
        self.takes_answer()
        got2 = self.page({"eval": f"[!!document.querySelector('{LAYER}'), window.__leaves]"},
                         {"eval": "document.querySelector('.ag-layer .frozen-bar button').click(), 1"},
                         {"until": f"!document.querySelector('{LAYER}')", "ms": 8000})
        self.assertEqual(got2[0]["eval"], [True, 0])
        self.assertEqual(got[1]["eval"], [True, 0, True])                # the text holds the mode: no way back started

    def answered_turn(self, rid, question, answer):
        """The owner answers rid elsewhere (its own words): the core gives the session the answer as a message, the
        session takes it — a turn of its own starts. Returns the answer's seq."""
        e = self.j.append("permission.answered", "shop", {"request_id": rid, "behavior": "allow", "channel": "telegram",
                                                             "owner": True, "answers": {question: answer}})
        self.ev("turn.started", "shop", marker=f"m{e['seq']}")
        return e["seq"]

    def takes_answer(self, text="—"):
        """The session takes the latest answer (the core's message about it) and ends that turn without a question."""
        from core import journal
        seq = max(e["seq"] for e in journal.read(self.j.path) if e["type"] in ("permission.answered", "question.dismissed"))
        self.ev("turn.started", "shop", marker=f"m{seq}")
        self.end_turn(text)

    def end_turn(self, text="—"):
        self.ev("turn.result", "shop", text=text)
        self.ev("turn.stopped", "shop")

    def test_a_session_working_on_the_answer_holds_the_mode_and_its_new_question_comes(self):
        self.ask("r1", "Как назовём очередь?")
        # __t — when the answered card left the screen (the answer recorded)
        gone = ("window.__t = null; new MutationObserver(() => { if (window.__t == null && !document.querySelector('.ag-layer .ag-slide .card'))"
                " window.__t = performance.now(); }).observe(document.body, {subtree: true, childList: true})")
        got = self.opened({"eval": gone + ", document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"},
                          {"typed": "orders-retry, но сначала проверь имя в Grafana"}, {"key": "Enter"},
                          {"until": "!document.querySelector('.ag-layer .ag-empty').hidden", "ms": 8000}, init=TIMERS)
        from core import journal
        seq = max(e["seq"] for e in journal.read(self.j.path) if e["type"] == "permission.answered")
        self.ev("turn.started", "shop", marker=f"m{seq}")   # the session takes the answer: a turn of its own
        self.ev("session.said", "shop", text="Проверяю имя в **Grafana**.")
        # past the moment right after the answer (GRACE in main.js): the session works on it, the mode waits with its words
        got = self.page({"until": "window.__t != null && performance.now() - window.__t > 3500", "ms": 8000},
                        {"eval": f"[!!document.querySelector('{LAYER}'), document.querySelector('.ag-empty .hint').textContent]"},
                        self.shot("working-light.png", theme="light"))
        self.assertEqual(got[1]["eval"], [True, "Сессия работает над вашим ответом — новый вопрос появится здесь."])
        self.ask("r2", "Имя orders-retry занято. Берём orders-retry-2?")
        got = self.page({"until": f"{COUNT} === '1 из 1'", "ms": 8000}, {"until": f"{CTX}?.rows.length === 3", "ms": 8000}, {"eval": CTX})
        rows = got[2]["eval"]["rows"]
        self.assertIn("Как назовём очередь?", rows[0])                    # the earlier question
        self.assertIn("orders-retry, но сначала проверь имя в Grafana", rows[1])   # the owner's own words as the answer
        self.assertIn("Проверяю имя в Grafana.", rows[2])
        self.assertEqual(got[2]["eval"]["md"], 1)                         # the page's markdown
        # the session ends the turn without a new question after the answer: the mode goes back to the hub
        self.answered_turn("r2", "Имя orders-retry занято. Берём orders-retry-2?", "Да")
        self.end_turn("Готово")
        got = self.page({"until": f"!document.querySelector('{LAYER}')", "ms": 15000})
        self.assertTrue(got[0]["until"])

    def test_the_context_is_the_earlier_answer_and_the_whole_turn_it_started_also_after_the_card(self):
        m = self.j.append("message.received", None, {"to": "shop", "text": "Сделай очередь повторов", "channel": "web", "owner": True})
        self.ev("turn.started", "shop", marker=f"m{m['seq']}")
        self.ev("session.said", "shop", text="Работаю над очередью повторов.")
        self.ask("r1", "Как назовём очередь?")
        self.end_turn()
        self.answered_turn("r1", "Как назовём очередь?", "orders-retry")
        self.ev("session.said", "shop", text="Принято, называю **orders-retry**.")
        self.ask("r2", "Выкатываем на стейдж сейчас?")
        got = self.opened({"until": f"{CTX}?.rows.length === 3", "ms": 8000}, {"eval": CTX},
                          self.shot("context-light.png", theme="light"))
        c = got[5]["eval"]
        self.assertIn("Как назовём очередь?", c["rows"][0])
        self.assertIn("orders-retry", c["rows"][1])
        self.assertIn("Принято, называю orders-retry.", c["rows"][2])
        self.assertFalse(any("Работаю над очередью" in r for r in c["rows"]))   # the turn before the answer is not in it
        self.assertTrue(c["left"] and c["inside"] and not c["hidden"])
        self.assertEqual(c["acts"], 0)                                     # no "Reply", reactions or jumps of the feed behind
        # the session goes on talking after the card: its words come into the box later
        self.ev("session.said", "shop", text="Пока жду решения, проверяю миграции.")
        got = self.page({"until": f"{CTX}?.rows.length === 4", "ms": 8000}, {"eval": CTX})
        self.assertIn("Пока жду решения, проверяю миграции.", got[1]["eval"]["rows"][3])

    def test_someone_elses_turn_between_the_answer_and_the_question_stays_out(self):
        self.ask("r1", "Как назовём очередь?")
        self.end_turn()
        self.answered_turn("r1", "Как назовём очередь?", "orders-retry")
        self.ev("session.said", "shop", text="Принято, отдала исполнителю.")
        self.end_turn()
        m = self.j.append("message.received", None, {"to": "shop", "text": "Готово: очередь заведена", "channel": "session",
                                                     "owner": False, "sender": "worker-1"})
        self.ev("turn.started", "shop", marker=f"m{m['seq']}")
        self.ev("session.said", "shop", text="Исполнитель отчитался, разбираю его отчёт.")
        self.ask("r2", "Выкатываем на стейдж сейчас?")
        got = self.opened({"until": f"{CTX}?.rows.length === 3", "ms": 8000}, {"eval": CTX})
        rows = got[5]["eval"]["rows"]
        self.assertIn("Как назовём очередь?", rows[0])
        self.assertIn("orders-retry", rows[1])
        self.assertIn("Принято, отдала исполнителю.", rows[2])
        self.assertFalse(any("Исполнитель отчитался" in r for r in rows))   # someone else's turn is not in it

    def test_without_an_earlier_answer_the_context_is_the_turn_of_the_question(self):
        m = self.j.append("message.received", None, {"to": "shop", "text": "Посмотри логи", "channel": "web", "owner": True})
        self.ev("turn.started", "shop", marker=f"m{m['seq']}")
        self.ev("session.said", "shop", text="Смотрю логи сервиса после выката.")
        self.ask("r1", "Откатываем выпуск?")
        self.ev("session.said", "shop", text="Жду решения по откату.")
        got = self.opened({"until": f"{CTX}?.rows.length === 2", "ms": 8000}, {"eval": CTX})
        rows = got[5]["eval"]["rows"]
        self.assertIn("Смотрю логи сервиса после выката.", rows[0])
        self.assertIn("Жду решения по откату.", rows[1])
        # a question with nothing before it: the card alone
        self.ev("turn.stopped", "shop")
        self.ev("turn.started", "shop", marker=None, prompt_head="x")
        self.ask("r2", "Второй?")
        got = self.page({"until": f"{COUNT} === '1 из 2'", "ms": 8000}, {"key": "ArrowRight"},
                        {"until": f"{COUNT} === '2 из 2' && {CTX}?.hidden === true", "ms": 8000})
        self.assertTrue(got[2]["until"])

    def test_a_long_context_scrolls_in_its_box_and_a_phone_folds_it_above_the_card(self):
        self.ask("r1", "Как назовём очередь?")
        self.end_turn()
        self.answered_turn("r1", "Как назовём очередь?", "orders-retry")
        for i in range(12):
            self.ev("session.said", "shop", text=f"Шаг {i}: проверила конфиг очереди, миграции и права сервиса — всё сходится, иду дальше по плану выката.")
        self.ask("r2", "Выкатываем на стейдж сейчас?")
        got = self.opened({"until": f"{CTX}?.rows.length === 14", "ms": 8000}, {"eval": CTX},
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
        self.ev("session.said", "shop", text="Принято, начинаю.")
        for i in range(260):
            self.tool("shop", f"t{i}", f"echo {i}")   # a long turn: more rows than one page of the history
        self.ask("r2", "Выкатываем на стейдж сейчас?")
        got = self.opened({"until": f"{CTX}?.rows.length === 3", "ms": 15000}, {"eval": CTX})
        rows = got[5]["eval"]["rows"]
        self.assertIn("Как назовём очередь?", rows[0])
        self.assertIn("Принято, начинаю.", rows[2])

    def test_a_question_closed_elsewhere_while_typing_keeps_the_text(self):
        self.ask("r1", "Как назовём очередь?")
        self.ask("r2", "Второй?")
        got = self.opened({"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"},
                          {"typed": "orders-retry"})
        self.ev("permission.answered", "shop", request_id="r1", behavior="allow", channel="telegram", owner=True,
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
        self.assertEqual(got[7]["eval"], "#/s/shop")                 # Back closed the mode, not the session
        self.assertTrue(got[11]["until"])
        self.assertEqual(got[12]["eval"], got[4]["eval"])               # no stray entries pile up

    def test_a_frozen_card_outlives_esc_and_a_reopened_question_is_live_again(self):
        self.ask("r1", "Как назовём очередь?")
        self.ask("r2", "Второй?")
        self.opened({"eval": "document.querySelector('.ag-layer .ag-slide:not([inert]) textarea.other').focus(), 1"},
                    {"typed": "orders-retry"})
        self.ev("permission.answered", "shop", request_id="r1", behavior="allow", channel="telegram", owner=True,
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
        self.assertNotIn("r1", self.pending())
