"""Context-dependent PII (names, organisations, roles) via a local Ollama model.

The model only LISTS sensitive strings as JSON. It never rewrites the text, so
it cannot silently drop or alter content. Every string it returns is then
located in the original text; anything it invented is discarded.
"""
import json
import re
import urllib.error
import urllib.request

from ..models import Entity

DEFAULT_MODEL = "qwen2.5:1.5b-instruct"
DEFAULT_URL = "http://localhost:11434/api/chat"
LABELS = ["PERSON", "ORGANIZATION", "JOB_TITLE", "LOCATION"]

SYSTEM = """You find sensitive information in text. Do NOT rewrite the text.
Return JSON listing every sensitive string exactly as it appears in the text.
Labels: PERSON (names of people), ORGANIZATION (companies, hospitals, schools),
JOB_TITLE (professions/roles), LOCATION (cities, addresses, places).

Example input: Ravi works as a nurse at Apollo Hospital in Pune.
Example output: {"entities":[{"text":"Ravi","label":"PERSON"},{"text":"nurse","label":"JOB_TITLE"},{"text":"Apollo Hospital","label":"ORGANIZATION"},{"text":"Pune","label":"LOCATION"}]}"""


def _schema(labels):
    return {
        "type": "object",
        "properties": {"entities": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"},
                           "label": {"type": "string", "enum": labels}},
            "required": ["text", "label"]}}},
        "required": ["entities"],
    }


def find_spans(text: str, needle: str):
    """All whole-word occurrences of needle in text, as (start, end).

    Whole-word matching stops "Ravi" from hitting inside "Ravindra".
    """
    pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
    return [m.span() for m in re.finditer(pattern, text)]


class LLMDetector:
    name = "llm"

    def __init__(self, model=DEFAULT_MODEL, url=DEFAULT_URL, labels=None, timeout=120):
        self.model = model
        self.url = url
        self.labels = labels or LABELS
        self.timeout = timeout

    def _ask(self, text: str) -> list:
        body = {
            "model": self.model,
            "stream": False,
            "format": _schema(self.labels),
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": text}],
        }
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            reply = json.loads(resp.read())["message"]["content"]
        return json.loads(reply).get("entities", [])

    def detect(self, text: str) -> list:
        try:
            raw = self._ask(text)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise RuntimeError(
                f"Could not reach Ollama at {self.url}. Is it running and is "
                f"'{self.model}' pulled? ({e})") from e
        found = []
        for item in raw:
            value = (item.get("text") or "").strip()
            label = item.get("label")
            if not value or label not in self.labels:
                continue
            for start, end in find_spans(text, value):   # hallucination guard
                found.append(Entity(start, end, value, label, self.name, 0.8))
        return found
