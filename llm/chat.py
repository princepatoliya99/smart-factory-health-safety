"""
RAG + LLM chat for the Smart Factory Health & Safety Analytics System.

How it works (RAG pipeline):
  1. Your question is embedded with Gemini.
  2. The most relevant knowledge chunks are retrieved from MongoDB
     (factory_db.rag_chunks — built by llm/rag_build.py) using cosine similarity.
  3. Gemini answers ONLY from those retrieved chunks, in plain simple English.

If the RAG index was not built yet, it falls back to answering from
results/*.json directly.

Ask things like:
    "which machine should I fix first and why?"
    "is M-011 safe to run this week?"
    "which operator needs safety retraining?"
    "what is our biggest downtime cause?"

Needs:  export GOOGLE_API_KEY="..."   (free: https://aistudio.google.com)
Run:    python llm/chat.py            (after: python llm/rag_build.py)
"""
import json
import math
import os
import sys
from pathlib import Path

import requests
from pymongo import MongoClient

BASE = Path(__file__).resolve().parent.parent
RESULTS = BASE / "results"
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "factory_db"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/"
              "models/gemini-2.0-flash:generateContent")
EMBED_URL = ("https://generativelanguage.googleapis.com/v1beta/"
             "models/text-embedding-004:embedContent")
TOP_K = 4


def gemini(prompt, api_key):
    r = requests.post(f"{GEMINI_URL}?key={api_key}",
                      json={"contents": [{"parts": [{"text": prompt}]}]},
                      timeout=60)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def embed(text, api_key):
    r = requests.post(f"{EMBED_URL}?key={api_key}",
                      json={"content": {"parts": [{"text": text}]}},
                      timeout=60)
    r.raise_for_status()
    return r.json()["embedding"]["values"]


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def retrieve(query, chunks, api_key):
    qv = embed(query, api_key)
    scored = [(cosine(qv, c["embedding"]), c) for c in chunks]
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:TOP_K]]


def fallback_context():
    ctx = {}
    for f in ["summary.json", "risk.json"]:
        p = RESULTS / f
        if p.exists():
            ctx[f] = json.loads(p.read_text())
    if "risk.json" in ctx:
        ctx["risk.json"] = {"machines": ctx["risk.json"]["machines"]}
    return json.dumps(ctx, default=str)[:20000]


def main():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print('export GOOGLE_API_KEY="..." first (free key: https://aistudio.google.com)')
        sys.exit(1)

    db = MongoClient(MONGO_URI)[DB_NAME]
    chunks = list(db["rag_chunks"].find({}, {"_id": 0}))
    use_rag = bool(chunks)
    if use_rag:
        print(f"🏭 Factory AI assistant ready — RAG index loaded "
              f"({len(chunks)} chunks from MongoDB).")
    else:
        print("🏭 Factory AI assistant ready — RAG index not built, "
              "using summary fallback.\n   (Run python llm/rag_build.py for full RAG.)")
    print("Ask anything (type 'exit' to quit).\n")

    while True:
        q = input("You: ").strip()
        if q.lower() in ("exit", "quit"):
            break
        if not q:
            continue
        try:
            if use_rag:
                top = retrieve(q, chunks, api_key)
                context = "\n\n".join(f"[{c['chunk_id']}] {c['text']}" for c in top)
                prompt = (
                    "You are a factory analytics assistant for a CNC/VMC "
                    "manufacturing plant. Answer the user's question using ONLY "
                    "the retrieved factory records below. Be specific: mention "
                    "machine/operator IDs and exact numbers. End with one practical "
                    "recommended action. Plain simple English, no jargon.\n\n"
                    f"RETRIEVED RECORDS:\n{context}\n\nQuestion: {q}"
                )
            else:
                prompt = (
                    "You are a factory analytics assistant. Answer from the JSON "
                    "below in plain simple English with exact numbers and IDs, "
                    "plus one practical action.\n\n"
                    f"DATA:\n{fallback_context()}\n\nQuestion: {q}"
                )
            print("\nAssistant:", gemini(prompt, api_key).strip(), "\n")
        except Exception as e:
            print(f"\n(error: {e})\n")


if __name__ == "__main__":
    main()
