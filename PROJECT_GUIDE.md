# Smart Factory Health & Safety Analytics System
### Complete Build Guide — Big Data Analytics course project

**What this is:** a big-data analytics system for CNC/VMC manufacturing factories.
It watches two things factories lose money on — **safety violations** and **unplanned
machine breakdowns** — and tells the owner exactly which machines to fix first.

**Stack:** MongoDB only (61,015 documents) + Python aggregation pipelines +
Chart.js dashboard + Gemini LLM chat layer.

---

## 1. Project structure

```
smart-factory-health-safety/
├── app.py                     # Flask operator web app (login, faults, photo upload, fix workflow)
├── templates/                 # login, dashboard, machines, faults, entry forms (gradient UI)
├── static/style.css           # gradient theme
├── uploads/                   # fault photos (created at runtime)
├── data/generate_data.py      # creates 61k factory log documents -> MongoDB
├── mongo/setup.py             # creates all indexes (the "big data" performance part)
├── analytics/pipelines.py     # 5 analytics modules (MongoDB aggregation pipelines)
├── dashboard/index.html       # gradient Chart.js dashboard (reads results/*.json)
├── llm/rag_build.py           # builds the RAG knowledge index (MongoDB rag_chunks)
├── llm/chat.py                # RAG chat: ask in plain English (Gemini + MongoDB)
├── llm/weekly_report.py       # LLM-written weekly manager report
├── results/                   # pipeline outputs (JSON) — regenerated on each run
├── requirements.txt
└── PROJECT_GUIDE.md           # this file
```

## 2. Setup (do once)

**Step 1 — Install MongoDB** (Community 8.0, free)
- Ubuntu: follow https://www.mongodb.com/docs/manual/tutorial/install-mongodb-on-ubuntu/
- Windows/Mac: download from https://www.mongodb.com/try/download/community
- Start it: `mongod` (default port 27017, no login needed locally)

**Step 2 — Python packages**
```
pip install -r requirements.txt
```
(needs `pymongo` and `requests`)

**Step 3 — Free Gemini API key** (for the LLM chat + weekly report)
- Go to https://aistudio.google.com → "Get API key" → free tier
- `export GOOGLE_API_KEY="paste-your-key"` (Windows: `set GOOGLE_API_KEY=...`)

## 3. Run the whole system

**A. The operator web app (the main demo — interactive, not a static page)**
```
python app.py
```
Open **http://localhost:5000** — login as operator `O-001`, password `factory123`.
- **Dashboard:** live machine status — open faults, risk scores, overdue maintenance
- **Machines:** click any machine → its faults, safety history, breakdowns
- **Report fault:** pick machine + fault type + **upload a photo** → saved in MongoDB,
  machine instantly shows the open fault
- **Fix:** open the fault → write what you did → "Mark as fixed" → machine status updates
- **Safety Check / Log Shift / Log Breakdown:** enter daily logs from the app —
  they go straight into MongoDB
- **Recompute analytics:** re-runs all 5 MongoDB pipelines on the live data, then
  opens the gradient analytics dashboard

**B. The analytics pipeline alone (no app)**
```
python data/generate_data.py      # 1. load 61,015 factory documents into MongoDB
python mongo/setup.py             # 2. create indexes
python analytics/pipelines.py     # 3. run all 5 analytics modules -> results/*.json
python llm/rag_build.py           # 4. build RAG knowledge index (needs API key)
python -m http.server 8000        # 5. open http://localhost:8000/dashboard/
```

LLM parts (need the API key from step 3):
```
python llm/chat.py                # RAG chat: "which machine should I fix first and why?"
python llm/weekly_report.py       # writes llm/weekly_report.md
```

## 4. The 5 modules (what each one does)

| # | Module | Input collection | What MongoDB computes |
|---|--------|------------------|----------------------|
| M1 | Safety violation analytics | `safety_checks` (27k) | violations per machine / operator / checklist item + 12-week trend |
| M2 | Preventive maintenance | `maintenance` + `machines` | hours until service due, overdue list, MTBF, cost per machine |
| M3 | Machine risk score | M1 + M2 + M4 outputs | 0–100 score per machine → 🔴/🟡/🟢 (40% violations, 30% downtime, 20% overdue, 10% OEE) |
| M4 | Downtime & OEE | `shift_logs` (27k) + `breakdowns` | OEE = availability × performance × quality per machine; downtime by cause |
| M5 | Tool life analytics | `tool_changes` (5.7k) | avg % of rated life used per tool type; early-failure alerts |

## 5. The data (what's inside MongoDB)

- **25 machines** — CNC Lathe ×8, VMC ×8, Drilling ×4, Power Press ×3, Grinding ×2
- **40 operators** across 3 shifts (A/B/C)
- **365 days** of logs: one safety checklist + one production log per machine per shift per day
- 6-item safety checklist: PPE, chuck guard, emergency-stop test, lockout/tagout, coolant level, floor clear
- Breakdown causes: spindle failure, tool crash, coolant pump, electrical, hydraulic, chuck, servo, belt
- 3 machines are deliberately "problem machines" so the analytics have a clear story
  (in a real factory this would be real log data)

## 6. How to demo it (5 minutes)

**The app (interactive — this is the main demo):**
1. Login as `O-001` / `factory123` → dashboard shows live machine health.
2. Open a red machine (M-003) → **Report fault** → upload a photo, describe it →
   the fault instantly appears as OPEN on that machine.
3. Open the fault → write fix notes → **Mark as fixed** → machine goes back to 0 open faults.
4. Enter a **Safety Check** with one "fail" → hit **Recompute analytics** → the new
   violation appears in the charts.
5. Open **Analytics** → gradient dashboard with all 5 modules.

**The data story (for faculty):** 61k MongoDB documents, aggregation pipelines,
RAG + LLM chat (`python llm/chat.py` after `python llm/rag_build.py`).

## 7. How to explain it to faculty (the BDA angle)

- **Volume:** 61,015 documents across 7 collections — real multi-collection scale,
  not a toy CSV.
- **Analytics engine = MongoDB aggregation pipelines** (`$match` → `$group` →
  `$sort`), the same pattern used in production big-data systems — no pandas,
  the database does the heavy lifting.
- **Velocity-ready:** time-series log data (daily safety/production logs);
  pipelines filter by date windows (30/90 days) exactly like a streaming setup would.
- **Indexes** on `(machine_id, date)` etc. — dashboard queries return in
  milliseconds instead of full collection scans.
- **AI/LLM layer:** RAG pipeline — every machine gets an embedded knowledge chunk
  in MongoDB (`rag_chunks`); questions are embedded, the top-4 relevant chunks are
  retrieved by cosine similarity, and Gemini answers from them. Plus natural-language
  → aggregation fallback and auto-generated weekly reports.

## 8. Resume line

> Built a big-data health & safety analytics platform for CNC/VMC manufacturing —
> 61k MongoDB documents, 5 aggregation-pipeline modules (safety, predictive
> maintenance, risk scoring, OEE, tool-life), gradient Chart.js dashboard, and a
> RAG + Gemini-LLM chat interface for natural-language factory queries.

## 9. Extending it (if faculty asks "what's next?")

- Replace the data generator with real log entry: a simple form that inserts into
  `safety_checks` / `shift_logs` (the pipelines need no changes).
- Add Kafka: stream the daily logs through a Kafka topic into MongoDB
  (faculty mentioned Kafka — the schema already fits: one JSON message per log).
- Add Spark: run the OEE aggregation as a Spark job for the "we used Spark" checkbox.
