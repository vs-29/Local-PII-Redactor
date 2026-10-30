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

    @classmethod
    def available(cls, model="en_core_web_sm") -> bool:
        try:
            import spacy
            spacy.load(model)
            return True
        except Exception:
            return False

    def detect(self, text: str) -> list:
        return [Entity(e.start_char, e.end_char, e.text, LABEL_MAP[e.label_], self.name, 0.7)
                for e in self.nlp(text).ents if e.label_ in LABEL_MAP]
