"""Run several detectors, merge their results, redact, and optionally audit."""
from .detectors.regex_detector import RegexDetector
from .models import Entity, RedactionResult
from .redact import redact

# Last tie-breaker, for detections with the same length and score.
# Same order as the default scores: regex 1.0 > llm 0.8 > ner 0.7.
SOURCE_PRIORITY = {"regex": 0, "llm": 1, "ner": 2}


def merge(entities: list) -> list:
    """Resolve overlaps: longest span wins, then higher score, then source priority.

    The score matters for labels: spaCy's small English model often tags
    Indian names as places or organisations, while the LLM (higher score)
    reads the context and labels them PERSON.
    """
    candidates = sorted(set(entities), key=lambda e: (-len(e), -e.score,
                                                      SOURCE_PRIORITY.get(e.source, 9), e.start))
    kept = []
    for e in candidates:
        if not any(e.overlaps(k) for k in kept):
            kept.append(e)
    return sorted(kept, key=lambda e: e.start)


class Pipeline:
    def __init__(self, detectors=None, style="tag", auditor=None):
        self.detectors = detectors if detectors is not None else [RegexDetector()]
        self.style = style
        self.auditor = auditor

    @classmethod
    def default(cls, use_llm=True, use_ner=True, **llm_kwargs):
        """Regex always; NER if spaCy is installed; LLM if requested."""
        detectors = [RegexDetector()]
        if use_ner:
            from .detectors.ner_detector import NERDetector
            if NERDetector.available():
                detectors.append(NERDetector())
        if use_llm:
            from .detectors.llm_detector import LLMDetector
            detectors.append(LLMDetector(**llm_kwargs))
        return cls(detectors)

    def detect(self, text: str) -> list:
        found = []
        for d in self.detectors:
            found.extend(d.detect(text))
        return merge(found)

    def run(self, text: str, source_name: str = None) -> RedactionResult:
        result = redact(text, self.detect(text), style=self.style)
        if self.auditor:
            self.auditor.log(result, source_name=source_name,
                             detectors=[d.name for d in self.detectors])
        return result
