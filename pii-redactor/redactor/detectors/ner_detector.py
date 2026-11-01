"""Optional statistical NER via spaCy.

Install:  pip install spacy && python -m spacy download en_core_web_sm
If spaCy is not installed the pipeline simply skips this detector.
"""
from ..models import Entity

# spaCy label -> our label
LABEL_MAP = {"PERSON": "PERSON", "ORG": "ORGANIZATION",
             "GPE": "LOCATION", "LOC": "LOCATION", "FAC": "LOCATION"}


class NERDetector:
    name = "ner"

    def __init__(self, model="en_core_web_sm"):
        import spacy  # imported here so the package works without spaCy
        self.nlp = spacy.load(model)
        self._doc = None

    @classmethod
    def available(cls, model="en_core_web_sm") -> bool:
        try:
            import spacy
            spacy.load(model)
            return True
        except Exception:
            return False

    def _parse(self, text: str):
        # detect() and is_name_like() run on the same text, so parse it only once
        if self._doc is None or self._doc.text != text:
            self._doc = self.nlp(text)
        return self._doc

    def detect(self, text: str) -> list:
        return [Entity(e.start_char, e.end_char, e.text, LABEL_MAP[e.label_], self.name, 0.7)
                for e in self._parse(text).ents if e.label_ in LABEL_MAP]

    def is_name_like(self, text: str, start: int, end: int) -> bool:
        """Does text[start:end] read as a name here? "Ask Will" yes, "Will you" no.

        Uses the part-of-speech tag: a name is tagged PROPN or NOUN (lowercase
        "priya" gets either, depending on the sentence), a verb is AUX or VERB.
        A common noun like "hope" also passes, which over-redacts but never leaks.
        ALL-CAPS words always pass: spaCy is unreliable on them ("Thanks, WILL" -> AUX).
        """
        if text[start:end].isupper():
            return True
        span = self._parse(text).char_span(start, end, alignment_mode="expand")
        if span is None:
            return True   # can't tell, so redact (the safe side)
        return all(t.pos_ in ("PROPN", "NOUN") for t in span)
