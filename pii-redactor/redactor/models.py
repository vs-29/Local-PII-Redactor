"""Shared data types used by every detector and by the redaction step."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Entity:
    """One piece of PII found in the text, located by character position.

    start/end follow Python slicing: text[start:end] == self.text
    """
    start: int
    end: int
    text: str
    label: str            # e.g. EMAIL, PHONE, PERSON, ORGANIZATION
    source: str           # which detector found it: "regex", "ner", "llm"
    score: float = 1.0    # confidence, 0..1 (regex hits are 1.0)

    def __len__(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "Entity") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass
class RedactionResult:
    original: str
    redacted: str
    entities: list           # list[Entity] actually redacted
    mapping: dict = field(default_factory=dict)   # tag -> original text

    def restore(self, text: str = None) -> str:
        """Put the original values back (e.g. into an LLM's answer)."""
        text = self.redacted if text is None else text
        # Tags end with ']' so [PERSON_1] can never match inside [PERSON_10].
        # Sorting just makes the replacement order predictable.
        for tag in sorted(self.mapping, key=len, reverse=True):
            text = text.replace(tag, self.mapping[tag])
        return text
