"""
Smart Factory — Operator Web App (Flask)

Interactive app, not a static page:
  - Operator login (operator ID + password)
  - Live machine status: open faults, risk level, maintenance due
  - Report a machine fault with photo upload -> saved in MongoDB
  - Fix a fault from the app -> status updates live everywhere
  - Data entry: safety checklist, shift production log, breakdown log
  - "Recompute analytics" button -> re-runs the MongoDB pipelines in-process
  - Analytics page: the gradient dashboard

Run:
    python app.py
Then open http://localhost:5000  (login: any operator ID, e.g. O-001, password: factory123)
"""
import os
import sys
from datetime import datetime
from pathlib import Path

from bson import ObjectId
from flask import (Flask, flash, redirect, render_template, request,
                   send_file, send_from_directory, session, url_for)
from pymongo import MongoClient
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from analytics.pipelines import main as run_pipelines  # noqa: E402

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = "factory_db"
UPLOAD_DIR = BASE / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_EXT = {"png", "jpg", "jpeg", "webp"}

app = Flask(__name__)
app.secret_key = "factory-demo-secret-key"
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB photos

db = MongoClient(MONGO_URI)[DB_NAME]
# demo passwords (added once, kept afterwards)
db.operators.update_many({"password": {"$exists": False}},
                         {"$set": {"password": "factory123"}})

SAFETY_ITEMS = [
    ("ppe_worn", "PPE worn"),
    ("chuck_guard_closed", "Chuck guard closed"),
    ("emergency_stop_tested", "Emergency stop tested"),
    ("lockout_tagout_done", "Lockout / tagout done"),
    ("coolant_level_ok", "Coolant level OK"),
    ("floor_area_clear", "Floor area clear"),
]
FAULT_TYPES = ["Mechanical failure", "Electrical fault", "Coolant / hydraulic leak",
               "Tool / chuck damage", "Safety guard broken", "Abnormal noise / vibration",
               "Other"]


def current_user():
    oid = session.get("operator_id")
    return db.operators.find_one({"operator_id": oid}) if oid else None


def login_required(fn):
    from functools import wraps

    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*a, **kw)

    return wrapper


def machine_status(mid):
    """Live status card data for one machine, read fresh from MongoDB."""
    m = db.machines.find_one({"machine_id": mid}, {"_id": 0})
    open_faults = db.fault_reports.count_documents(
        {"machine_id": mid, "status": "open"})
    last = db.maintenance.find_one({"machine_id": mid}, sort=[("service_date", -1)])
    next_due = last["next_due_hours"] if last else m["service_interval_hours"]
    remaining = round(next_due - m.get("current_runtime_hours", 0), 1)
    maint = "overdue" if remaining < 0 else ("due_soon" if remaining <= 50 else "ok")
    # risk from latest pipeline run (recomputed on demand)
    risk_doc = None
    rp = BASE / "results" / "risk.json"
    if rp.exists():
        import json
        for r in json.loads(rp.read_text())["machines"]:
            if r["machine_id"] == mid:
                risk_doc = r
                break
    return {"machine": m, "open_faults": open_faults,
            "maint_status": maint, "hours_left": remaining,
            "risk": risk_doc["risk_score"] if risk_doc else None,
            "level": risk_doc["level"] if risk_doc else "green"}


# ------------------------------------------------------------------ auth
@app.route("/")
def index():
    return redirect(url_for("dashboard" if current_user() else "login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        op = db.operators.find_one({
            "operator_id": request.form["operator_id"].strip().upper(),
            "password": request.form["password"],
        })
        if op:
            session["operator_id"] = op["operator_id"]
            return redirect(url_for("dashboard"))
        flash("Wrong operator ID or password. Try O-001 / factory123.", "error")
    ops = list(db.operators.find({}, {"_id": 0, "operator_id": 1, "name": 1})
               .sort("operator_id").limit(40))
    return render_template("login.html", operators=ops)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------- dashboard
@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    machines = [machine_status(m["machine_id"])
                for m in db.machines.find({}, {"machine_id": 1}).sort("machine_id")]
    open_faults = db.fault_reports.count_documents({"status": "open"})
    red = sum(1 for x in machines if x["level"] == "red")
    overdue = sum(1 for x in machines if x["maint_status"] == "overdue")
    recent_faults = list(db.fault_reports.find({"status": "open"})
                         .sort("date", -1).limit(5))
    return render_template("dashboard.html", user=user, machines=machines,
                           open_faults=open_faults, red=red, overdue=overdue,
                           recent_faults=recent_faults)


# -------------------------------------------------------------- machines
@app.route("/machines")
@login_required
def machines():
    ms = [machine_status(m["machine_id"])
          for m in db.machines.find({}, {"machine_id": 1}).sort("machine_id")]
    return render_template("machines.html", machines=ms, user=current_user())


@app.route("/machine/<mid>")
@login_required
def machine_detail(mid):
    st = machine_status(mid)
    if not st["machine"]:
        flash("Unknown machine.", "error")
        return redirect(url_for("machines"))
    faults = list(db.fault_reports.find({"machine_id": mid}).sort("date", -1).limit(10))
    safety = list(db.safety_checks.find({"machine_id": mid}).sort("date", -1).limit(5))
    breakdowns = list(db.breakdowns.find({"machine_id": mid}).sort("date", -1).limit(5))
    return render_template("machine_detail.html", st=st, faults=faults,
                           safety=safety, breakdowns=breakdowns, user=current_user())


# ---------------------------------------------------------------- faults
@app.route("/faults")
@login_required
def faults():
    status = request.args.get("status", "open")
    q = {} if status == "all" else {"status": status}
    flist = list(db.fault_reports.find(q).sort("date", -1))
    return render_template("faults.html", faults=flist, status=status,
                           user=current_user())


@app.route("/faults/new", methods=["GET", "POST"])
@login_required
def report_fault():
    user = current_user()
    if request.method == "POST":
        photo_name = None
        f = request.files.get("photo")
        if f and f.filename:
            ext = f.filename.rsplit(".", 1)[-1].lower()
            if ext not in ALLOWED_EXT:
                flash("Photo must be png/jpg/jpeg/webp.", "error")
                return redirect(request.url)
            photo_name = (datetime.now().strftime("%Y%m%d_%H%M%S_")
                          + secure_filename(f.filename))
            f.save(UPLOAD_DIR / photo_name)
        db.fault_reports.insert_one({
            "machine_id": request.form["machine_id"],
            "operator_id": user["operator_id"],
            "operator_name": user["name"],
            "shift": user["shift"],
            "date": datetime.now(),
            "fault_type": request.form["fault_type"],
            "description": request.form["description"].strip(),
            "photo": photo_name,
            "status": "open",
            "fixed_date": None,
            "fix_notes": None,
        })
        flash(f"Fault reported on {request.form['machine_id']} — it now shows "
              "as an open fault on that machine.", "ok")
        return redirect(url_for("faults"))
    machines = list(db.machines.find({}, {"_id": 0, "machine_id": 1, "type": 1})
                    .sort("machine_id"))
    pre = request.args.get("machine", "")
    return render_template("report_fault.html", machines=machines,
                           fault_types=FAULT_TYPES, pre=pre, user=user)


@app.route("/faults/<fid>", methods=["GET", "POST"])
@login_required
def fault_detail(fid):
    fault = db.fault_reports.find_one({"_id": ObjectId(fid)})
    if not fault:
        flash("Fault not found.", "error")
        return redirect(url_for("faults"))
    if request.method == "POST":  # mark as fixed
        db.fault_reports.update_one(
            {"_id": fault["_id"]},
            {"$set": {"status": "fixed", "fixed_date": datetime.now(),
                      "fix_notes": request.form.get("fix_notes", "").strip(),
                      "fixed_by": current_user()["operator_id"]}})
        flash(f"Fault on {fault['machine_id']} marked FIXED — machine status updated.",
              "ok")
        return redirect(url_for("machine_detail", mid=fault["machine_id"]))
    return render_template("fault_detail.html", fault=fault, user=current_user())


@app.route("/uploads/<fname>")
@login_required
def uploaded_file(fname):
    return send_from_directory(UPLOAD_DIR, fname)


# ------------------------------------------------------------ data entry
@app.route("/safety-check", methods=["GET", "POST"])
@login_required
def safety_check():
    user = current_user()
    if request.method == "POST":
        checks, violations = {}, 0
        for key, _label in SAFETY_ITEMS:
            val = request.form.get(key, "pass")
            checks[key] = val
            violations += (val == "fail")
        db.safety_checks.insert_one({
            "machine_id": request.form["machine_id"],
            "operator_id": user["operator_id"],
            "shift": user["shift"],
            "date": datetime.now(),
            "checks": checks,
            "violations": violations,
            "source": "app",
        })
        flash(f"Safety check saved ({violations} violations). "
              "Recompute analytics to see it in the reports.", "ok")
        return redirect(url_for("dashboard"))
    machines = list(db.machines.find({}, {"_id": 0, "machine_id": 1}).sort("machine_id"))
    return render_template("safety_check.html", machines=machines,
                           items=SAFETY_ITEMS, user=user)


@app.route("/log-shift", methods=["GET", "POST"])
@login_required
def log_shift():
    user = current_user()
    if request.method == "POST":
        run_h = float(request.form["run_hours"])
        dt_h = float(request.form["downtime_hours"])
        parts = int(request.form["parts_produced"])
        defects = int(request.form["defects"])
        db.shift_logs.insert_one({
            "machine_id": request.form["machine_id"],
            "shift": user["shift"],
            "date": datetime.now(),
            "planned_hours": 8.0,
            "run_hours": run_h,
            "downtime_hours": dt_h,
            "parts_produced": parts,
            "defects": defects,
            "source": "app",
        })
        # keep machine runtime roughly in sync for maintenance maths
        db.machines.update_one({"machine_id": request.form["machine_id"]},
                               {"$inc": {"current_runtime_hours": run_h}})
        flash("Shift log saved.", "ok")
        return redirect(url_for("dashboard"))
    machines = list(db.machines.find({}, {"_id": 0, "machine_id": 1}).sort("machine_id"))
    return render_template("log_shift.html", machines=machines, user=user)


@app.route("/log-breakdown", methods=["GET", "POST"])
@login_required
def log_breakdown():
    user = current_user()
    if request.method == "POST":
        db.breakdowns.insert_one({
            "machine_id": request.form["machine_id"],
            "date": datetime.now(),
            "shift": user["shift"],
            "downtime_hours": float(request.form["downtime_hours"]),
            "cause": request.form["cause"],
            "repair_cost_rs": int(request.form.get("repair_cost_rs") or 0),
            "source": "app",
        })
        flash("Breakdown logged — it will appear in downtime analytics.", "ok")
        return redirect(url_for("dashboard"))
    machines = list(db.machines.find({}, {"_id": 0, "machine_id": 1}).sort("machine_id"))
    causes = ["Spindle bearing failure", "Tool crash", "Coolant pump failure",
              "Electrical panel fault", "Hydraulic leak", "Chuck jaw damage",
              "Servo motor fault", "Belt breakage", "Other"]
    return render_template("log_breakdown.html", machines=machines,
                           causes=causes, user=user)


# ------------------------------------------------------------- analytics
@app.route("/recompute", methods=["POST"])
@login_required
def recompute():
    run_pipelines()
    flash("Analytics recomputed from live MongoDB data.", "ok")
    return redirect(url_for("analytics"))


@app.route("/analytics")
@login_required
def analytics():
    return send_file(BASE / "dashboard" / "index.html")


@app.route("/results/<path:fname>")
@login_required
def results(fname):
    return send_from_directory(BASE / "results", fname)


if __name__ == "__main__":
    print("Open http://localhost:5000  (login: O-001 / factory123)")
    app.run(host="0.0.0.0", port=5000, debug=False)
