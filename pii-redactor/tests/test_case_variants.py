"""Case-variant matching: the LLM says "Priya", the text also has "PRIYA" / "priya".

Run:  python -m unittest discover -s tests   (from the pii-redactor folder)
The spaCy tests are skipped when spaCy or en_core_web_sm isn't installed.
"""
import unittest

from redactor.detectors.llm_detector import LLMDetector, looks_like_name
from redactor.detectors.ner_detector import NERDetector
from redactor.models import Entity
from redactor.pipeline import Pipeline
from redactor.redact import redact

HAS_SPACY = NERDetector.available()


class FakeLLM(LLMDetector):
    """Returns canned answers instead of calling Ollama."""
    def __init__(self, answer, **kw):
        super().__init__(**kw)
        self.answer = answer

    def _ask(self, text):
        return self.answer


def spans(llm, text):
    return [e.text for e in sorted(llm.detect(text), key=lambda e: e.start)]


PRIYA = [{"text": "Priya", "label": "PERSON"}]


class FallbackTests(unittest.TestCase):
    """Without spaCy: Title Case and ALL CAPS variants count, lowercase doesn't."""

    def test_caps_variant_found_lowercase_skipped(self):
        text = "Priya called. Later I met priya. Regards, PRIYA"
        self.assertEqual(spans(FakeLLM(PRIYA), text), ["Priya", "PRIYA"])

    def test_verb_will_not_redacted(self):
        llm = FakeLLM([{"text": "Will", "label": "PERSON"}])
        self.assertEqual(spans(llm, "Ask Will for it. I will call."), ["Will"])

    def test_entity_keeps_the_spelling_in_the_text(self):
        llm = FakeLLM([{"text": "priya", "label": "PERSON"}])
        self.assertEqual(spans(llm, "Regards, PRIYA"), ["PRIYA"])

    def test_multi_word_value_matches_any_case(self):
        llm = FakeLLM([{"text": "Priya Sharma", "label": "PERSON"}])
        self.assertEqual(spans(llm, "cc priya sharma"), ["priya sharma"])

    def test_variant_check_is_pluggable(self):
        text = "Priya and priya"
        self.assertEqual(spans(FakeLLM(PRIYA, variant_check=lambda t, s, e: True), text),
                         ["Priya", "priya"])
        self.assertEqual(spans(FakeLLM(PRIYA, variant_check=lambda t, s, e: False), text),
                         ["Priya"])

    def test_looks_like_name(self):
        text = "PRIYA Priya priya"
        self.assertTrue(looks_like_name(text, 0, 5))
        self.assertTrue(looks_like_name(text, 6, 11))
        self.assertFalse(looks_like_name(text, 12, 17))


class SameTagTests(unittest.TestCase):
    """All spellings of one value share a tag."""
    TEXT = "priya called. Later Priya wrote. Regards, PRIYA"

    def run_redact(self):
        ents = [Entity(m, m + 5, self.TEXT[m:m + 5], "PERSON", "llm")
                for m in (0, 20, 42)]
        return redact(self.TEXT, ents)

    def test_one_tag_for_all_spellings(self):
        self.assertEqual(self.run_redact().redacted,
                         "[PERSON_1] called. Later [PERSON_1] wrote. Regards, [PERSON_1]")

    def test_mapping_prefers_normal_spelling(self):
        # "priya" comes first, but "Priya" is the spelling put back
        self.assertEqual(self.run_redact().mapping, {"[PERSON_1]": "Priya"})

    def test_restore_is_still_exact(self):
        r = self.run_redact()
        self.assertEqual(r.restore(), self.TEXT)
        self.assertEqual(r.restore("Reply to [PERSON_1]"), "Reply to Priya")

    def test_different_labels_keep_different_tags(self):
        text = "Pune met pune"
        ents = [Entity(0, 4, "Pune", "LOCATION", "llm"), Entity(9, 13, "pune", "PERSON", "llm")]
        self.assertEqual(redact(text, ents).redacted, "[LOCATION_1] met [PERSON_1]")


@unittest.skipUnless(HAS_SPACY, "spaCy + en_core_web_sm not installed")
class SpacyTests(unittest.TestCase):
    """With spaCy: the part-of-speech tag decides."""

    @classmethod
    def setUpClass(cls):
        cls.ner = NERDetector()

    def check(self, text, word):
        start = text.index(word)
        return self.ner.is_name_like(text, start, start + len(word))

    def test_lowercase_name_counts_as_propn_or_noun(self):
        # spaCy tags the same word differently depending on the sentence
        self.assertTrue(self.check("Later I talked to priya yesterday.", "priya"))   # PROPN
        self.assertTrue(self.check("I talked to priya about it.", "priya"))          # NOUN

    def test_all_caps_always_counts(self):
        self.assertTrue(self.check("Thanks, WILL", "WILL"))   # spaCy says AUX here

    def test_verb_rejected(self):
        self.assertFalse(self.check("Ask Will for it. I will call.", "will"))

    def test_pipeline_wires_pos_check_into_llm(self):
        pipe = Pipeline.default(use_llm=True)
        ner = next(d for d in pipe.detectors if isinstance(d, NERDetector))
        llm = next(d for d in pipe.detectors if isinstance(d, LLMDetector))
        self.assertEqual(llm.variant_check, ner.is_name_like)

    def test_end_to_end_with_fake_llm(self):
        ner = NERDetector()
        llm = FakeLLM(PRIYA, variant_check=ner.is_name_like)
        text = "Priya called. Later I talked to priya about it. Regards, PRIYA"
        self.assertEqual(spans(llm, text), ["Priya", "priya", "PRIYA"])


if __name__ == "__main__":
    unittest.main()
