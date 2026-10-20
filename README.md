# Smart Factory Health & Safety Analytics System
Big Data Analytics course project. We built this for CNC/VMC manufacturing factories — it watches safety violations and unplanned machine breakdowns, and tells you which machines to fix first.
## What it does
Five analytics modules, all running as MongoDB aggregation pipelines:
1. **Safety violation analytics** — violations per machine / operator / checklist item, plus a 12-week trend2. **Predictive maintenance alerts** — hours until service is due, overdue list, MTBF per machine3. **Machine risk scoring** — every machine gets a 0–100 score → red / yellow / green4. **Downtime & OEE tracking** — OEE = availability × performance × quality, downtime by cause5. **Tool life alerts** — flags tools that fail before their rated life
Measured on our data: 3 red machines (M-003, M-011, M-019), 4 overdue + 2 due-soon maintenance jobs, average OEE 78.3%.
## The operator web app (the main demo)
Interactive Flask app, not a static page. Login with `O-001` / `factory123`.
- Dashboard with live machine health- Report a fault on any machine, with a photo upload — it shows up as OPEN instantly- Fix workflow: write what you did, mark it fixed, machine status updates- Enter safety checks, shift logs and breakdowns straight from the app- "Recompute analytics" re-runs all 5 pipelines on the live data
## The data
- 61,015 documents across 7 collections in MongoDB- 25 machines (CNC Lathe, VMC, Drilling, Power Press, Grinding), 40 operators, 365 days of logs- One safety checklist + one production log per machine per shift per day
## AI chat layer
RAG pipeline: every machine gets an embedded knowledge chunk in MongoDB, questions are embedded, the top matches are retrieved by cosine similarity, and Gemini answers from them. `python llm/chat.py` — e.g. "which machine should I fix first and why?" `python llm/weekly_report.py` writes a plain-English weekly manager report.
## Run it
- MongoDB Community running locally (port 27017)- `pip install -r requirements.txt`- `python data/generate_data.py` — load the 61k documents- `python mongo/setup.py` — create indexes- `python analytics/pipelines.py` — run the 5 modules- `python app.py` — open http://localhost:5000, login O-001 / factory123
The LLM parts need a free Gemini key from aistudio.google.com (no card): `export GOOGLE_API_KEY="your-key"`, then `python llm/rag_build.py` and `python llm/chat.py`.
Full step-by-step guide, demo script and how to explain the BDA angle to faculty: see **PROJECT_GUIDE.md**.
