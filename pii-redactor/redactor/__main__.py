"""Command line:  python -m redactor [options] [FILE]

Reads FILE (or stdin), prints the redacted text.
Examples:
  python -m redactor --no-llm notes.txt
  echo "Call Priya on 9876543210" | python -m redactor
  python -m redactor report.txt --out report.redacted.txt --map map.json --audit
"""
import argparse
import json
import sys

from .audit import AuditLog
from .pipeline import Pipeline


def main(argv=None):
    # Windows consoles/pipes may default to cp1252, which can't encode █ or non-Latin names
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):      # StringIO in tests has no reconfigure()
            stream.reconfigure(encoding="utf-8")

    p =argparse.ArgumentParser(prog="redactor", description="Local PII redactor")
    p.add_argument("file", nargs="?", help="input text file (default: stdin)")
    p.add_argument("--out", help="write redacted text here instead of stdout")
    p.add_argument("--map", help="write tag->original mapping JSON here (keep it private!)")
    p.add_argument("--no-llm", action="store_true", help="skip the Ollama detector")
    p.add_argument("--no-ner", action="store_true", help="skip spaCy even if installed")
    p.add_argument("--model", default=None, help="Ollama model name")
    p.add_argument("--mask", action="store_true", help="█ masking instead of tags")
    p.add_argument("--audit", action="store_true", help="append an audit record")
    p.add_argument("--audit-file", default="redaction_audit.jsonl",
                   help="audit log path (default: %(default)s)")
    p.add_argument("--show", action="store_true", help="list detections on stderr")
    a = p.parse_args(argv)

    if a.file:
        with open(a.file, encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()
    llm_kwargs = {"model": a.model} if a.model else {}
    pipe = Pipeline.default(use_llm=not a.no_llm, use_ner=not a.no_ner, **llm_kwargs)
    pipe.style = "mask" if a.mask else "tag"
    if a.audit:
        pipe.auditor = AuditLog(a.audit_file)

    try:
        result = pipe.run(text, source_name=a.file)
    except RuntimeError as e:
        sys.exit(f"error: {e}\n(tip: use --no-llm to run without Ollama)")

    if a.show:
        for e in result.entities:
            print(f"  {e.label:<14} {e.source:<6} {e.text!r}", file=sys.stderr)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(result.redacted)
    else:
        sys.stdout.write(result.redacted)
    if a.map:
        with open(a.map, "w", encoding="utf-8") as f:
            json.dump(result.mapping, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
