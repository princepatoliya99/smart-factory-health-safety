"""
Generates a plain-English weekly factory health & safety report with the LLM.

Reads results/*.json, asks Gemini to write the report, saves llm/weekly_report.md.

Needs:  export GOOGLE_API_KEY="..."
Run:    python llm/weekly_report.py
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
RESULTS = BASE / "results"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/"
              "models/gemini-2.0-flash:generateContent")


def main():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print('export GOOGLE_API_KEY="..." first (free key: https://aistudio.google.com)')
        sys.exit(1)
    data = {}
    for f in ["summary.json", "risk.json", "safety.json", "oee.json",
              "maintenance.json", "tools.json"]:
        p = RESULTS / f
        if p.exists():
            data[f] = json.loads(p.read_text())
    if not data:
        print("Run python analytics/pipelines.py first.")
        sys.exit(1)

    prompt = (f"You are writing the weekly health & safety report for a CNC/VMC "
              f"manufacturing plant, week ending {date.today()}. "
              "Use ONLY the analytics JSON below. Write in plain simple English a "
              "short manager can act on. Structure:\n"
              "1. Headline (one line: is the plant getting safer or worse?)\n"
              "2. Top 3 risks (machine IDs, what is wrong, exact numbers)\n"
              "3. Maintenance due this week\n"
              "4. Safety: worst machines/operators and the most-failed checklist item\n"
              "5. One paragraph: recommended actions for next week\n"
              "Keep it under 400 words.\n\nDATA:\n" + json.dumps(data, default=str)[:25000])

    r = requests.post(f"{GEMINI_URL}?key={api_key}",
                      json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=90)
    r.raise_for_status()
    report = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    out = BASE / "llm" / "weekly_report.md"
    out.write_text(f"# Weekly Factory Health & Safety Report — {date.today()}\n\n{report}\n")
    print(f"Report saved to {out}")


if __name__ == "__main__":
    main()
