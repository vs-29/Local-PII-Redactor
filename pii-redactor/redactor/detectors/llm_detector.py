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


_ITEM = re.compile(r"\{[^{}]*\}")


def parse_entities(reply: str) -> list:
    """The model's JSON reply -> list of {"text", "label"} dicts.

    If the reply was cut off (output limit hit, usually because a small model
    got stuck repeating itself), keep the complete items that made it out.
    """
    try:
        return json.loads(reply).get("entities", [])
    except json.JSONDecodeError:
        items = []
        for m in _ITEM.finditer(reply):
            try:
                items.append(json.loads(m.group()))
            except json.JSONDecodeError:
                pass
        return [i for i in items if isinstance(i, dict)]


def find_spans(text: str, needle: str):
    """All whole-word occurrences of needle in text, as (start, end).

    Whole-word matching stops "Ravi" from hitting inside "Ravindra".
    """
    pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
    return [m.span() for m in re.finditer(pattern, text)]


def chunk_text(text: str, max_chars: int = 3000, overlap: int = 200) -> list:
    """Split text into pieces of at most max_chars for the model's context window.

    Cuts at a paragraph, line, sentence or word break when one is in the second
    half of the window. Neighbouring pieces overlap, so a name cut by one
    boundary appears whole in the next piece.
    """
    if len(text) <= max_chars:
        return [text]
    chunks, start = [], 0
    while True:
        end = min(start + max_chars, len(text))
        if end < len(text):
            window = text[start:end]
            for sep in ("\n\n", "\n", ". ", " "):
                cut = window.rfind(sep, max_chars // 2)
                if cut != -1:
                    end = start + cut + len(sep)
                    break
        chunks.append(text[start:end])
        if end == len(text):
            return chunks
        # start the next piece at a word break inside the overlap
        space = text.find(" ", end - overlap, end)
        start = space + 1 if space != -1 else end


class LLMDetector:
    name = "llm"

    def __init__(self, model=DEFAULT_MODEL, url=DEFAULT_URL, labels=None, timeout=120,
                 chunk_chars=3000, overlap=200, max_output_tokens=1024):
        if not 0 <= overlap < chunk_chars // 2:
            raise ValueError("overlap must be smaller than half of chunk_chars")
        self.model = model
        self.url = url
        self.labels = labels or LABELS
        self.timeout = timeout
        self.chunk_chars = chunk_chars
        self.overlap = overlap
        self.max_output_tokens = max_output_tokens

    def _ask(self, text: str) -> list:
        body = {
            "model": self.model,
            "stream": False,
            "format": _schema(self.labels),
            # num_predict caps the reply, so a repetition loop can't run until the timeout
            "options": {"temperature": 0, "num_predict": self.max_output_tokens},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": text}],
        }
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            reply = json.loads(resp.read())["message"]["content"]
        return parse_entities(reply)

    def detect(self, text: str) -> list:
        # collect (value, label) pairs from every chunk; a dict keeps first-seen order
        values = {}
        for chunk in chunk_text(text, self.chunk_chars, self.overlap):
            try:
                raw = self._ask(chunk)
            except TimeoutError as e:
                raise RuntimeError(
                    f"Ollama took longer than {self.timeout}s on a {len(chunk)}-char "
                    f"chunk. Try a larger timeout or smaller chunk_chars.") from e
            except (urllib.error.URLError, ConnectionError) as e:
                raise RuntimeError(
                    f"Could not reach Ollama at {self.url}. Is it running and is "
                    f"'{self.model}' pulled? ({e})") from e
            for item in raw:
                value = (item.get("text") or "").strip()
                label = item.get("label")
                if value and label in self.labels:
                    values[(value, label)] = None

        # search the FULL text, so no per-chunk offsets are needed
        found = []
        for value, label in values:
            for start, end in find_spans(text, value):   # hallucination guard
                found.append(Entity(start, end, value, label, self.name, 0.8))
        return found
