"""Pattern-based detection for PII with a fixed shape.

Fast, deterministic and needs no model. Checksums (Luhn, Verhoeff) are used
where they exist, to cut false positives on random digit strings.
"""
import re

from ..models import Entity

# --- checksum helpers -------------------------------------------------------

def luhn_valid(number: str) -> bool:
    digits = [int(d) for d in number if d.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_V_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],
        [3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],[5,9,8,7,6,0,4,3,2,1],
        [6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],
        [9,8,7,6,5,4,3,2,1,0]]
_V_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],
        [8,9,1,6,0,4,3,5,2,7],[9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],
        [2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]


def verhoeff_valid(number: str) -> bool:
    """Aadhaar numbers carry a Verhoeff check digit."""
    c = 0
    for i, d in enumerate(reversed([int(x) for x in number if x.isdigit()])):
        c = _V_D[c][_V_P[i % 8][d]]
    return c == 0


# --- patterns ---------------------------------------------------------------
# (label, compiled regex, optional validator on the matched string)

PATTERNS = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
    ("URL", re.compile(r"\bhttps?://[^\s<>\"']+"), None),
    ("AADHAAR", re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b"), verhoeff_valid),
    ("PAN", re.compile(r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b"), None),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), luhn_valid),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"), None),
    # Indian mobile (+91 optional) or a generic international number
    ("PHONE", re.compile(
        r"(?<![\w+])(?:(?:\+|00)91[ -]?)?[6-9]\d{4}[ -]?\d{5}\b"
        r"|(?<![\w+])\+\d{1,3}[ -]?\(?\d{1,4}\)?(?:[ -]?\d{2,4}){2,4}\b"), None),
    ("IP_ADDRESS", re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"), None),
    ("DATE_OF_BIRTH", re.compile(
        r"(?i)\b(?:dob|d\.o\.b\.?|date of birth|born on)\s*[:\-]?\s*"
        r"(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})"), None),
]


class RegexDetector:
    name = "regex"

    def __init__(self, labels=None):
        """labels: optional set of labels to enable (default: all)."""
        self.patterns = [p for p in PATTERNS if labels is None or p[0] in labels]

    def detect(self, text: str) -> list:
        found = []
        for label, pattern, validator in self.patterns:
            for m in pattern.finditer(text):
                # if the pattern has a capture group, redact only that part
                g = 1 if m.re.groups and m.group(1) else 0
                start, end = m.span(g)
                value = text[start:end]
                if validator and not validator(value):
                    continue
                found.append(Entity(start, end, value, label, self.name))
        return found
