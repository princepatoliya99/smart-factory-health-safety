"""
RAG index builder — turns factory analytics into searchable knowledge.

Creates one text chunk per machine (its full health profile) plus global
summary chunks, embeds them with Gemini, and stores them in the MongoDB
collection `rag_chunks`. The chat layer retrieves the most relevant chunks
for each question (cosine similarity) and the LLM answers from them.

Run AFTER the analytics pipelines:
    export GOOGLE_API_KEY="..."
    python analytics/pipelines.py
    python llm/rag_build.py
"""
import json
import os
import sys
from pathlib import Path

import requests
from pymongo import MongoClient

BASE = Path(__file__).resolve().parent.parent
RESULTS = BASE / "results"
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "factory_db"
EMBED_URL = ("https://generativelanguage.googleapis.com/v1beta/"
             "models/text-embedding-004:embedContent")


def embed(text, api_key):
    r = requests.post(f"{EMBED_URL}?key={api_key}",
                      json={"content": {"parts": [{"text": text}]}},
                      timeout=60)
    r.raise_for_status()
    return r.json()["embedding"]["values"]


def build_chunks():
    risk = json.loads((RESULTS / "risk.json").read_text())["machines"]
    safety = json.loads((RESULTS / "safety.json").read_text())
    maint = {m["machine_id"]: m
             for m in json.loads((RESULTS / "maintenance.json").read_text())["machines"]}
    oee = {m["machine_id"]: m
           for m in json.loads((RESULTS / "oee.json").read_text())["per_machine"]}
    s = json.loads((RESULTS / "summary.json").read_text())

    chunks = []
    for m in risk:
        mid = m["machine_id"]
        mt = maint.get(mid, {})
        oe = oee.get(mid, {})
        chunks.append({
            "chunk_id": f"machine-{mid}",
            "text": (
                f"Machine {mid} ({m['type']}): risk score {m['risk_score']}/100 "
                f"({m['level'].upper()} risk). Safety violations in last 90 days: "
                f"{m['violations_90d']}. Downtime in last 90 days: {m['downtime_90d']} "
                f"hours. Maintenance status: {mt.get('status', 'unknown')} "
                f"({mt.get('hours_remaining', '?')} runtime hours left before service; "
                f"MTBF {mt.get('mtbf_hours', '?')} hours). OEE last 30 days: "
                f"{round(oe.get('oee', 0) * 100, 1)}% (availability "
                f"{round(oe.get('availability', 0) * 100, 1)}%, performance "
                f"{round(oe.get('performance', 0) * 100, 1)}%, quality "
                f"{round(oe.get('quality', 0) * 100, 1)}%). "
                f"Parts produced: {oe.get('parts_produced', '?')}, "
                f"defects: {oe.get('defects', '?')}."
            ),
        })

    viol_items = ", ".join(f"{i['item'].replace('_', ' ')} ({i['fails']} fails)"
                           for i in safety["per_item"][:3])
    chunks.append({
        "chunk_id": "global-safety",
        "text": (
            f"Plant safety summary (last 90 days): {s['total_violations_90d']} total "
            f"safety violations. Most-failed checklist items: {viol_items}. "
            f"Highest-risk machines: {', '.join(s['red_machines'])}. "
            f"Worst operators: " + ", ".join(
                f"{o['_id']} ({o.get('name', '')}, {o['total_violations']} violations)"
                for o in safety["per_operator"][:3]) + "."
        ),
    })
    chunks.append({
        "chunk_id": "global-maintenance",
        "text": (
            f"Maintenance summary: {s['overdue_machines']} machines overdue for "
            f"service, {s['due_soon_machines']} due within 50 runtime hours. "
            f"Overdue machines: "
            + ", ".join(m["machine_id"] for m in maint.values()
                        if m["status"] == "overdue") + ". "
            f"Top downtime cause: {s['top_downtime_cause']}."
        ),
    })
    chunks.append({
        "chunk_id": "global-oee",
        "text": (
            f"OEE summary (last 30 days): plant average OEE "
            f"{round(s['avg_oee_30d'] * 100, 1)}%. Lowest OEE machines: "
            + ", ".join(f"{m['machine_id']} ({round(m['oee'] * 100, 1)}%)"
                        for m in sorted(oee.values(), key=lambda x: x["oee"])[:3]) + "."
        ),
    })
    tools = json.loads((RESULTS / "tools.json").read_text())
    chunks.append({
        "chunk_id": "global-tools",
        "text": (
            "Tool life summary: " + "; ".join(
                f"{t['tool_type']} averages {t['avg_life_used_pct']}% of rated life"
                for t in tools["by_type"]) + ". " +
            ("Alerts: " + " ".join(a["message"] for a in tools["alerts"])
             if tools["alerts"] else "No tool alerts.")
        ),
    })
    return chunks


def main():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print('export GOOGLE_API_KEY="..." first (free key: https://aistudio.google.com)')
        sys.exit(1)
    if not (RESULTS / "summary.json").exists():
        print("Run python analytics/pipelines.py first.")
        sys.exit(1)

    chunks = build_chunks()
    print(f"Embedding {len(chunks)} chunks...")
    docs = []
    for c in chunks:
        docs.append({"chunk_id": c["chunk_id"], "text": c["text"],
                     "embedding": embed(c["text"], api_key)})
        print(f"  embedded {c['chunk_id']}")

    db = MongoClient(MONGO_URI)[DB_NAME]
    db["rag_chunks"].drop()
    db["rag_chunks"].insert_many(docs)
    db["rag_chunks"].create_index("chunk_id")
    print(f"RAG index ready: {len(docs)} chunks in factory_db.rag_chunks")


if __name__ == "__main__":
    main()
