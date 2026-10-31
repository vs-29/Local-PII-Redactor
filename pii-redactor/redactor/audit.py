"""Append-only JSONL audit log of what was redacted.

The log must not become a second copy of the PII, so original values are
stored only as salted SHA-256 hashes. With the same salt you can still check
"was this value redacted?" without the log revealing it.
"""
import hashlib
import json
import os
import warnings
from collections import Counter
from datetime import datetime, timezone


class AuditLog:
    def __init__(self, path="redaction_audit.jsonl", salt=None):
        self.path = path
        self.salt = salt if salt is not None else os.environ.get("PII_AUDIT_SALT", "")
        if not self.salt:
            warnings.warn("PII_AUDIT_SALT is not set: audit hashes of short values "
                          "(phone numbers, IDs) can be reversed by guessing.")

    def _hash(self, value: str) -> str:
        return hashlib.sha256((self.salt + value).encode()).hexdigest()[:16]

    def log(self, result, source_name=None, detectors=None):
        record = {
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": source_name,
            "detectors": detectors,
            "chars": len(result.original),
            "counts": dict(Counter(e.label for e in result.entities)),
            "entities": [{"start": e.start, "end": e.end, "label": e.label,
                          "detector": e.source, "score": e.score,
                          "value_hash": self._hash(e.text)} for e in result.entities],
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return record
