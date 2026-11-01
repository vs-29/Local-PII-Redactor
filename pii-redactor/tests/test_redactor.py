"""Run:  python -m unittest discover -s tests   (from the pii-redactor folder)
No Ollama needed: the LLM is replaced by a fake detector."""
import json
import os
import tempfile
import unittest

from redactor.audit import AuditLog
from redactor.detectors.llm_detector import LLMDetector, chunk_text, find_spans, parse_entities
from redactor.detectors.regex_detector import RegexDetector, _V_D, _V_P, luhn_valid, verhoeff_valid
from redactor.models import Entity
from redactor.pipeline import Pipeline, merge
from redactor.redact import redact

_V_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def make_aadhaar(first11: str) -> str:
    """Append a valid Verhoeff check digit."""
    c = 0
    for i, d in enumerate(reversed([int(x) for x in first11])):
        c = _V_D[c][_V_P[(i + 1) % 8][d]]
    return first11 + str(_V_INV[c])


class FakeLLM(LLMDetector):
    """Returns canned answers instead of calling Ollama."""
    def __init__(self, answer):
        super().__init__()
        self.answer = answer

    def _ask(self, text):
        return self.answer


def labels(text, **kw):
    return {(e.label, e.text) for e in RegexDetector(**kw).detect(text)}


class RegexTests(unittest.TestCase):
    def test_email_phone(self):
        got = labels("Mail a.b@x.co.in or call 9876543210 / +91-98765 43210")
        self.assertIn(("EMAIL", "a.b@x.co.in"), got)
        self.assertIn(("PHONE", "9876543210"), got)
        self.assertIn(("PHONE", "+91-98765 43210"), got)

    def test_aadhaar_checksum(self):
        good = make_aadhaar("23456789012")
        self.assertTrue(verhoeff_valid(good))
        spaced = f"{good[:4]} {good[4:8]} {good[8:]}"
        self.assertIn(("AADHAAR", spaced), labels(f"Aadhaar {spaced}"))
        bad = good[:-1] + str((int(good[-1]) + 1) % 10)
        self.assertNotIn("AADHAAR", {l for l, _ in labels(f"id {bad}")})

    def test_card_needs_luhn(self):
        self.assertTrue(luhn_valid("4111111111111111"))
        self.assertIn(("CREDIT_CARD", "4111 1111 1111 1111"), labels("card 4111 1111 1111 1111"))
        self.assertNotIn("CREDIT_CARD", {l for l, _ in labels("order 4111 1111 1111 1112")})

    def test_pan_ifsc_ip(self):
        got = labels("PAN ABCPS1234K IFSC HDFC0001234 host 192.168.1.20")
        self.assertIn(("PAN", "ABCPS1234K"), got)
        self.assertIn(("IFSC", "HDFC0001234"), got)
        self.assertIn(("IP_ADDRESS", "192.168.1.20"), got)

    def test_dob_redacts_only_date(self):
        self.assertIn(("DATE_OF_BIRTH", "01/02/1990"), labels("DOB: 01/02/1990"))

    def test_plain_numbers_ignored(self):
        self.assertEqual(labels("We sold 1500 units in 2024 for 250000 rupees."), set())


class LLMTests(unittest.TestCase):
    def test_whole_word_only(self):
        self.assertEqual(find_spans("Ravi met Ravindra", "Ravi"), [(0, 4)])

    def test_hallucinations_dropped(self):
        text = "Dr. Rao referred Priya Sharma to Apollo Hospital."
        llm = FakeLLM([{"text": "Priya Sharma", "label": "PERSON"},
                       {"text": "Rahul", "label": "PERSON"},          # not in text
                       {"text": "Apollo Hospital", "label": "ORGANIZATION"},
                       {"text": "x", "label": "NOT_A_LABEL"}])
        got = {(e.label, e.text) for e in llm.detect(text)}
        self.assertEqual(got, {("PERSON", "Priya Sharma"), ("ORGANIZATION", "Apollo Hospital")})

    def test_every_occurrence_found(self):
        llm = FakeLLM([{"text": "Priya", "label": "PERSON"}])
        self.assertEqual(len(llm.detect("Priya said Priya would come.")), 2)

    def test_parse_complete_reply(self):
        reply = '{"entities":[{"text":"Ravi","label":"PERSON"}]}'
        self.assertEqual(parse_entities(reply), [{"text": "Ravi", "label": "PERSON"}])

    def test_parse_cut_off_reply_keeps_complete_items(self):
        # what a repetition loop looks like when the output limit stops it
        reply = ('{"entities":[{"text":"Meera Pillai","label":"PERSON"},'
                 '{"text":"vendor contracts","label":"ORGANIZATION"},{"text":"vendor con')
        self.assertEqual([i["text"] for i in parse_entities(reply)],
                         ["Meera Pillai", "vendor contracts"])


class ChunkTests(unittest.TestCase):
    TEXT = "".join(f"Sentence {i} talks about budgets and plans. " for i in range(200))

    def test_short_text_is_one_chunk(self):
        self.assertEqual(chunk_text("hello", max_chars=100), ["hello"])

    def test_chunks_fit_and_cover_everything(self):
        chunks = chunk_text(self.TEXT, max_chars=500, overlap=50)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        self.assertTrue(self.TEXT.startswith(chunks[0]) and self.TEXT.endswith(chunks[-1]))
        # every character is in some chunk: consecutive chunks touch or overlap
        pos = 0
        for c in chunks:
            start = self.TEXT.find(c, max(0, pos - 50))
            self.assertLessEqual(start, pos)
            pos = start + len(c)
        self.assertEqual(pos, len(self.TEXT))

    def test_cuts_at_sentence_end(self):
        self.assertTrue(chunk_text(self.TEXT, max_chars=500, overlap=50)[0].endswith(". "))

    def test_every_chunk_is_asked_and_spans_use_full_text(self):
        seen = []

        class RecordingLLM(LLMDetector):
            def _ask(self, text):
                seen.append(text)
                return [{"text": "Vikram Singh", "label": "PERSON"}] if "Vikram" in text else []

        text = self.TEXT + "Signed by Vikram Singh."
        found = RecordingLLM(chunk_chars=500, overlap=50).detect(text)
        self.assertGreater(len(seen), 1)
        self.assertEqual([(e.start, e.end) for e in found], [(len(self.TEXT) + 10, len(text) - 1)])

    def test_bad_overlap_rejected(self):
        with self.assertRaises(ValueError):
            LLMDetector(chunk_chars=100, overlap=60)


class MergeAndRedactTests(unittest.TestCase):
    def test_longest_wins(self):
        a = Entity(0, 5, "Priya", "PERSON", "ner")
        b = Entity(0, 12, "Priya Sharma", "PERSON", "llm")
        self.assertEqual(merge([a, b]), [b])

    def test_regex_beats_llm_on_tie(self):
        a = Entity(0, 10, "9876543210", "PHONE", "regex")
        b = Entity(0, 10, "9876543210", "PERSON", "llm")
        self.assertEqual(merge([b, a]), [a])

    def test_llm_label_beats_ner_on_tie(self):
        # spaCy's small model tags "Ananya" as GPE (a place); the LLM says PERSON
        ner = Entity(0, 6, "Ananya", "LOCATION", "ner", 0.7)
        llm = Entity(0, 6, "Ananya", "PERSON", "llm", 0.8)
        self.assertEqual(merge([ner, llm]), [llm])

    def test_higher_score_wins_over_source_priority(self):
        a = Entity(0, 5, "Priya", "PERSON", "regex", 0.5)
        b = Entity(0, 5, "Priya", "PERSON", "custom", 0.9)
        self.assertEqual(merge([a, b]), [b])

    def test_email_beats_name_inside_it(self):
        text = "write to priya@x.com"
        pipe = Pipeline([RegexDetector(), FakeLLM([{"text": "priya", "label": "PERSON"}])])
        self.assertEqual(pipe.run(text).redacted, "write to [EMAIL_1]")

    def test_consistent_tags_and_restore(self):
        text = "Priya called Ravi. Later Priya emailed ravi@x.com."
        pipe = Pipeline([RegexDetector(), FakeLLM([{"text": "Priya", "label": "PERSON"},
                                                   {"text": "Ravi", "label": "PERSON"}])])
        r = pipe.run(text)
        self.assertEqual(r.redacted,
                         "[PERSON_1] called [PERSON_2]. Later [PERSON_1] emailed [EMAIL_1].")
        self.assertEqual(r.restore(), text)
        self.assertEqual(r.restore("Reply to [PERSON_2]"), "Reply to Ravi")

    def test_mask_style(self):
        r = redact("id 9876543210", RegexDetector().detect("id 9876543210"), style="mask")
        self.assertEqual(r.redacted, "id " + "█" * 10)
        self.assertEqual(r.mapping, {})


class AuditTests(unittest.TestCase):
    def test_log_has_no_raw_values(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "audit.jsonl")
            pipe = Pipeline([RegexDetector()], auditor=AuditLog(path, salt="s"))
            pipe.run("mail priya@x.com", source_name="t.txt")
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            self.assertNotIn("priya@x.com", raw)
            rec = json.loads(raw)
            self.assertEqual(rec["counts"], {"EMAIL": 1})


if __name__ == "__main__":
    unittest.main()
