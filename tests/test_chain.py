"""The context rule of «Только вопросы» (web/chain.js) on feed rows of the core's shape, in node: what the block next to a
question holds. Runs without a hub and without a browser."""
import json
import os
import shutil
import subprocess
import unittest

CHAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "chain.js")
NODE = shutil.which("node")


def run(rows, rid=None, msgs=None, more=False, what="context"):
    js = (f"import {{ context, answering }} from {json.dumps(CHAIN)};"
          f" const rows = {json.dumps(rows)}, msgs = {json.dumps(msgs or {})};"
          + (f" const c = context(rows, {json.dumps(rid)}, msgs, {json.dumps(more)});"
             " console.log(JSON.stringify(c && {ask: c.ask?.seq ?? null, answer: c.answer?.seq ?? null, said: c.said.map((x) => x.text), whole: c.whole}));"
             if what == "context" else " console.log(JSON.stringify(answering(rows, msgs)));"))
    r = subprocess.run([NODE, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


class Rows:
    """Feed rows as the core makes them (core/views.py): seq grows, ts follows it."""
    def __init__(self):
        self.rows, self.seq = [], 0

    def add(self, kind, **kw):
        self.seq += 1
        row = {"seq": self.seq, "ts": 1000.0 + self.seq, "kind": kind, **kw}
        self.rows.append(row)
        return row

    def owner(self, text, **kw):
        return self.add("in", id=f"m{self.seq + 1}", text=text, sender=None, **kw)

    def other(self, text, sender="worker-1"):
        return self.add("in", id=f"m{self.seq + 1}", text=text, sender=sender, **{"from": {"kind": "session", "name": sender}})

    def said(self, text):
        return self.add("out", text=text)

    def ask(self, rid, tool="AskUserQuestion"):
        return self.add("ask", request_id=rid, tool=tool)

    def answer(self, rid, relay=True, text="Да"):
        """The owner answers a card: the "↳" row and the core's message to the session with the same seq."""
        self.seq += 1
        a = {"seq": self.seq, "ts": 1000.0 + self.seq, "kind": "answer", "request_id": rid, "answers": {"q": text}}
        self.rows.append(a)
        if relay:
            q = next(x for x in self.rows if x["kind"] == "ask" and x["request_id"] == rid)
            self.rows.append({"seq": self.seq, "ts": a["ts"], "kind": "in", "id": f"m{self.seq}", "text": f"Ответ владельца на вопрос q{q['seq']}",
                              "sender": "владелец", "from": {"kind": "owner"}, "answer_to": f"q{q['seq']}"})
        return a


@unittest.skipUnless(NODE, "нужен node")
class Chain(unittest.TestCase):
    def test_the_turn_the_answer_started_before_and_after_the_card(self):
        r = Rows()
        r.owner("сделай очередь"); r.said("работаю"); p = r.ask("r1")
        a = r.answer("r1"); r.said("принято"); r.ask("r2"); r.said("жду решения")
        self.assertEqual(run(r.rows, "r2"), {"ask": p["seq"], "answer": a["seq"], "said": ["принято", "жду решения"], "whole": True})

    def test_someone_elses_turn_between_is_left_out(self):
        r = Rows()
        p = r.ask("r1"); a = r.answer("r1"); r.said("отдала исполнителю")
        r.other("готово"); r.said("разбираю отчёт"); r.ask("r2")
        self.assertEqual(run(r.rows, "r2")["said"], ["отдала исполнителю"])
        self.assertEqual(run(r.rows, "r2")["ask"], p["seq"])

    def test_the_owners_own_message_ends_the_chain(self):
        r = Rows()
        r.ask("r1"); r.answer("r1"); r.said("принято")
        r.owner("а теперь логи"); r.said("смотрю логи"); r.ask("r2")
        self.assertEqual(run(r.rows, "r2"), {"ask": None, "answer": None, "said": ["смотрю логи"], "whole": True})

    def test_a_line_typed_mid_turn_or_passed_to_a_mini_hub_starts_no_turn(self):
        r = Rows()
        r.ask("r1"); r.answer("r1"); r.said("принято")
        r.owner("кстати", midturn=True); r.add("in", id="mx", text="тебе", relayed="hub"); r.said("учла"); r.ask("r2")
        self.assertEqual(run(r.rows, "r2")["said"], ["принято", "учла"])

    def test_an_answer_waiting_in_the_queue_starts_nothing_yet(self):
        r = Rows()
        r.owner("сделай"); r.said("начала"); r.ask("r1")
        a = r.answer("r1"); r.said("пока не читала ответ"); r.ask("r3")
        msgs = {f"m{a['seq']}": {"state": "queued"}}
        got = run(r.rows, "r3", msgs)
        self.assertEqual((got["ask"], got["said"]), (None, ["начала", "пока не читала ответ"]))
        self.assertEqual(run(r.rows, msgs=msgs, what="answering"), "queued")

    def test_a_message_taken_together_with_the_answer_is_the_same_turn(self):
        r = Rows()
        p = r.ask("r1"); r.answer("r1"); r.other("fyi: заметка", sender="hub"); r.said("принято"); r.ask("r2")
        got = run(r.rows, "r2")
        self.assertEqual((got["ask"], got["said"]), (p["seq"], ["принято"]))
        self.assertEqual(run(r.rows, what="answering"), "working")

    def test_an_answer_taken_after_a_message_in_the_same_run_still_makes_it_the_answers_turn(self):
        r = Rows()
        r.owner("сделай"); p = r.ask("r1"); r.said("жду")
        r.other("fyi: заметка", sender="hub"); r.answer("r1"); r.said("принято"); r.ask("r2")
        self.assertEqual(run(r.rows, "r2")["ask"], p["seq"])

    def test_two_answers_taken_in_one_turn_show_the_latest(self):
        r = Rows()
        r.ask("r1"); p2 = r.ask("r2"); r.said("жду")
        r.answer("r1"); a2 = r.answer("r2"); r.said("по обоим принято"); r.ask("r3")
        got = run(r.rows, "r3")
        self.assertEqual((got["ask"], got["answer"]), (p2["seq"], a2["seq"]))

    def test_rows_that_begin_inside_someone_elses_turn_after_the_answer_ask_for_more(self):
        r = Rows()
        r.ask("r1"); r.answer("r1"); r.said("отдала исполнителю")
        r.other("готово"); r.said("разбираю"); r.ask("r2")
        tail = [x for x in r.rows if x["kind"] != "ask" or x["request_id"] == "r2"]
        tail = [x for x in tail if x["seq"] > r.rows[3]["seq"]]   # loaded from inside the answer's turn: its start is missing
        self.assertFalse(run(tail, "r2", more=True)["whole"])

    def test_the_same_question_asked_again_after_its_answer(self):
        r = Rows()
        p = r.ask("r1"); a = r.answer("r1"); r.said("ещё раз уточню"); r.ask("r1")
        got = run(r.rows, "r1")
        self.assertEqual((got["ask"], got["answer"], got["said"]), (p["seq"], a["seq"], ["ещё раз уточню"]))

    def test_a_card_closed_without_an_answer_is_not_an_answer(self):
        r = Rows()
        p = r.ask("r1"); r.said("до")
        r.seq += 1   # the core's message about the closed card: answer_to without a "↳" row
        r.rows.append({"seq": r.seq, "ts": 1000.0 + r.seq, "kind": "in", "id": f"m{r.seq}", "text": "закрыл", "sender": "владелец",
                       "from": {"kind": "owner"}, "answer_to": f"q{p['seq']}"})
        r.said("ладно"); r.ask("r2")
        got = run(r.rows, "r2")
        self.assertEqual((got["answer"], got["said"]), (None, ["ладно"]))   # the closing message is someone else's turn: skipped
        self.assertEqual(run(r.rows, what="answering"), None)
        closed = next(x for x in r.rows if x.get("answer_to"))
        self.assertIsNone(run(r.rows, msgs={closed["id"]: {"state": "queued"}}, what="answering"))   # nothing to wait for

    def test_an_answer_to_a_tool_permission_is_not_a_question_form(self):
        r = Rows()
        r.owner("почини"); r.said("нужен доступ"); r.ask("p1", tool="Bash"); r.answer("p1", relay=False); r.said("запустила"); r.ask("r2")
        got = run(r.rows, "r2")
        self.assertEqual((got["answer"], got["said"]), (None, ["нужен доступ", "запустила"]))

    def test_an_answer_inside_a_running_turn(self):
        r = Rows()
        p = r.ask("r1"); a = r.answer("r1", relay=False); r.said("продолжаю"); r.ask("r2")
        got = run(r.rows, "r2")
        self.assertEqual((got["ask"], got["answer"], got["said"]), (p["seq"], a["seq"], ["продолжаю"]))

    def test_rows_that_begin_inside_the_chain_ask_for_more(self):
        r = Rows()
        r.ask("r1"); r.answer("r1"); r.said("принято"); r.ask("r2")
        tail = [x for x in r.rows if x["seq"] > 2]   # the loaded rows begin after the answer
        self.assertFalse(run(tail, "r2", more=True)["whole"])
        self.assertIsNone(run(tail[:-1], "r2"))   # the question's row has not come yet
