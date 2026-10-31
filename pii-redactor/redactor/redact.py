"""Replace detected entities with numbered tags, by position.

Replacing by character position (not str.replace) means only the exact spans
that were detected change - "Ravi" is never replaced inside "Ravindra".
The same value always gets the same tag, so "Priya ... Priya" -> "[PERSON_1] ... [PERSON_1]".
"""
from .models import Entity, RedactionResult


def redact(text: str, entities: list, style: str = "tag") -> RedactionResult:
    """entities must not overlap (the pipeline guarantees this).

    style: "tag"  -> [PERSON_1]
           "mask" -> █████ (same length, not reversible)
    """
    ordered = sorted(entities, key=lambda e: e.start)

    # assign tags in reading order so numbering looks natural
    tag_for, counters, mapping = {}, {}, {}
    for e in ordered:
        key = (e.text, e.label)
        if key not in tag_for:
            counters[e.label] = counters.get(e.label, 0) + 1
            tag = f"[{e.label}_{counters[e.label]}]"
            tag_for[key] = tag
            mapping[tag] = e.text

    out, cursor = [], 0
    for e in ordered:
        out.append(text[cursor:e.start])
        out.append("█" * len(e) if style == "mask" else tag_for[(e.text, e.label)])
        cursor = e.end
    out.append(text[cursor:])

    return RedactionResult(original=text, redacted="".join(out), entities=ordered,
                           mapping={} if style == "mask" else mapping)
