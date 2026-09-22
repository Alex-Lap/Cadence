"""Scratch: eyeball a real syllabus extraction. Not part of the app."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()

from app.agent.tools.parse_syllabus import extract_text, parse_syllabus
from app.agent.tools.resolve_dates import resolve_dates

pdf_path = sys.argv[1]
term_start = sys.argv[2] if len(sys.argv) > 2 else None

text = extract_text(open(pdf_path, "rb").read())
print("=" * 60, "\nRAW TEXT (first 2000 chars)\n", "=" * 60)
print(text[:2000])

print("\n" + "=" * 60, "\nEXTRACTION\n", "=" * 60)
result = parse_syllabus(text, term_start=term_start)
if term_start:
    result = resolve_dates(result, date.fromisoformat(term_start))
for course in result.courses:
    print(f"\n{course.code} — {course.title}")
    for a in course.assignments:
        when = f"{a.due_at:%Y-%m-%d}" if a.due_at else "(no date) "
        flag = " [CATEGORY]" if a.is_category else ""
        conf = "" if a.due_date_confidence == "explicit" else f" ({a.due_date_confidence})"
        wk = f" wk{a.due_week}" if a.due_week else ""
        print(f"  {when}{conf}  {a.title:<40} weight={a.weight}{wk}{flag}")