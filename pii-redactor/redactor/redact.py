"""Replace detected entities with numbered tags, by position.

Replacing by character position (not str.replace) means only the exact spans
that were detected change - "Ravi" is never replaced inside "Ravindra".
The same value always gets the same tag, ignoring case, so
"Priya ... priya ... PRIYA" -> "[PERSON_1] ... [PERSON_1] ... [PERSON_1]".
"""
from .models import Entity, RedactionResult


def _key(e: Entity):
    return (e.text.casefold(), e.label)


def redact(text: str, entities: list, style: str = "tag") -> RedactionResult:
    """entities must not overlap (the pipeline guarantees this).

    style: "tag"  -> [PERSON_1]
           "mask" -> █████ (same length, not reversible)
    """
    ordered = sorted(entities, key=lambda e: e.start)

    # assign tags in reading order so numbering looks natural
    tag_for, counters, spellings = {}, {}, {}
    for e in ordered:
        key = _key(e)
        if key not in tag_for:
            counters[e.label] = counters.get(e.label, 0) + 1
            tag_for[key] = f"[{e.label}_{counters[e.label]}]"
        spellings.setdefault(key, []).append(e.text)

    # A tag maps back to one spelling. Prefer a normal one ("Priya") over
    # all-lowercase or ALL-CAPS, so restoring an AI tool's answer reads naturally.
    mapping = {}
    for key, tag in tag_for.items():
        forms = spellings[key]
        mapping[tag] = next((s for s in forms if not (s.islower() or s.isupper())), forms[0])

    out, cursor = [], 0
    for e in ordered:
        out.append(text[cursor:e.start])
        out.append("█" * len(e) if style == "mask" else tag_for[_key(e)])
        cursor = e.end
    out.append(text[cursor:])

    return RedactionResult(original=text, redacted="".join(out), entities=ordered,
                           mapping={} if style == "mask" else mapping)
