"""
Analytics engine — 5 modules, all powered by MongoDB aggregation pipelines.

  M1 safety       -> safety violations per machine / operator / checklist item + weekly trend
  M2 maintenance  -> service-due alerts, overdue list, MTBF, cost per machine
  M3 risk         -> red/yellow/green risk score per machine
  M4 oee          -> OEE (availability x performance x quality) + downtime by cause
  M5 tools        -> tool-life analytics, early-failure wastage, replacement alerts

Results are written to results/*.json for the dashboard and the LLM layer.

Run:  python analytics/pipelines.py
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "factory_db"
OUT = Path(__file__).resolve().parent.parent / "results"

NOW = datetime.now()
D90 = NOW - timedelta(days=90)
D30 = NOW - timedelta(days=30)


def save(name, data):
    OUT.mkdir(exist_ok=True)
    with open(OUT / name, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  wrote results/{name}")


# ------------------------------------------------------------------ M1 safety
def m1_safety(db):
    per_machine = list(db.safety_checks.aggregate([
        {"$match": {"date": {"$gte": D90}}},
        {"$group": {"_id": "$machine_id",
                    "total_violations": {"$sum": "$violations"},
                    "checks": {"$sum": 1}}},
        {"$sort": {"total_violations": -1}},
    ]))
    per_operator = list(db.safety_checks.aggregate([
        {"$match": {"date": {"$gte": D90}, "violations": {"$gt": 0}}},
        {"$group": {"_id": "$operator_id",
                    "total_violations": {"$sum": "$violations"},
                    "bad_checks": {"$sum": 1}}},
        {"$sort": {"total_violations": -1}},
        {"$limit": 10},
    ]))
    # join operator names
    ops = {o["operator_id"]: o["name"] for o in db.operators.find()}
    for r in per_operator:
        r["name"] = ops.get(r["_id"], r["_id"])

    per_item = []
    for item in ["ppe_worn", "chuck_guard_closed", "emergency_stop_tested",
                 "lockout_tagout_done", "coolant_level_ok", "floor_area_clear"]:
        fails = db.safety_checks.count_documents(
            {"date": {"$gte": D90}, f"checks.{item}": "fail"})
        per_item.append({"item": item, "fails": fails})
    per_item.sort(key=lambda x: -x["fails"])

    weekly = list(db.safety_checks.aggregate([
        {"$match": {"date": {"$gte": NOW - timedelta(days=84)}}},
        {"$group": {"_id": {"$isoWeek": "$date"},
                    "violations": {"$sum": "$violations"}}},
        {"$sort": {"_id": 1}},
    ]))
    return {
        "per_machine": per_machine,
        "per_operator": per_operator,
        "per_item": per_item,
        "weekly_trend": weekly,
        "total_violations_90d": sum(r["total_violations"] for r in per_machine),
    }


# ----------------------------------------------------------- M2 maintenance
def m2_maintenance(db):
    machines = list(db.machines.find())
    out = []
    for m in machines:
        last = db.maintenance.find_one(
            {"machine_id": m["machine_id"]}, sort=[("service_date", -1)])
        next_due = last["next_due_hours"] if last else m["service_interval_hours"]
        current = m.get("current_runtime_hours", 0)
        remaining = round(next_due - current, 1)
        if remaining < 0:
            status = "overdue"
        elif remaining <= 50:
            status = "due_soon"
        else:
            status = "ok"
        n_bd = db.breakdowns.count_documents({"machine_id": m["machine_id"]})
        mtbf = round(current / n_bd, 1) if n_bd else None
        cost = list(db.maintenance.aggregate([
            {"$match": {"machine_id": m["machine_id"]}},
            {"$group": {"_id": None, "total": {"$sum": "$cost_rs"}}},
        ]))
        out.append({
            "machine_id": m["machine_id"],
            "type": m["type"],
            "current_runtime_hours": current,
            "last_service": str(last["service_date"].date()) if last else None,
            "hours_remaining": remaining,
            "status": status,
            "mtbf_hours": mtbf,
            "breakdowns_total": n_bd,
            "maintenance_cost_rs": cost[0]["total"] if cost else 0,
        })
    out.sort(key=lambda x: x["hours_remaining"])
    return {
        "machines": out,
        "overdue": [x for x in out if x["status"] == "overdue"],
        "due_soon": [x for x in out if x["status"] == "due_soon"],
    }


# ------------------------------------------------------------------ M3 risk
def m3_risk(db, safety, maint, oee):
    viol = {r["_id"]: r["total_violations"] for r in safety["per_machine"]}
    max_v = max(viol.values()) or 1
    dt = {r["machine_id"]: r["downtime_90d"] for r in oee["downtime_per_machine"]}
    max_d = max(dt.values()) or 1
    oee_map = {r["machine_id"]: r["oee"] for r in oee["per_machine"]}
    maint_map = {m["machine_id"]: m for m in maint["machines"]}
    mtype = {m["machine_id"]: m["type"] for m in db.machines.find()}

    out = []
    for mid in mtype:
        v = viol.get(mid, 0) / max_v
        d = dt.get(mid, 0) / max_d
        overdue = 1 if maint_map[mid]["status"] == "overdue" else 0
        o = oee_map.get(mid, 0.8)
        score = round(100 * (0.40 * v + 0.30 * d + 0.20 * overdue + 0.10 * (1 - o)), 1)
        level = "red" if score >= 60 else ("yellow" if score >= 30 else "green")
        out.append({
            "machine_id": mid,
            "type": mtype[mid],
            "risk_score": score,
            "level": level,
            "violations_90d": viol.get(mid, 0),
            "downtime_90d": round(dt.get(mid, 0), 1),
            "maintenance_status": maint_map[mid]["status"],
            "oee_30d": round(o, 3),
        })
    out.sort(key=lambda x: -x["risk_score"])
    return {
        "machines": out,
        "red": [x for x in out if x["level"] == "red"],
        "yellow": [x for x in out if x["level"] == "yellow"],
        "green": [x for x in out if x["level"] == "green"],
    }


# ------------------------------------------------------------------- M4 oee
def m4_oee(db):
    per_machine = list(db.shift_logs.aggregate([
        {"$match": {"date": {"$gte": D30}}},
        {"$group": {"_id": "$machine_id",
                    "planned": {"$sum": "$planned_hours"},
                    "run": {"$sum": "$run_hours"},
                    "parts": {"$sum": "$parts_produced"},
                    "defects": {"$sum": "$defects"}}},
    ]))
    ideal = {m["machine_id"]: m["ideal_parts_per_hour"] for m in db.machines.find()}
    rows = []
    for r in per_machine:
        mid = r["_id"]
        availability = r["run"] / r["planned"] if r["planned"] else 0
        perf = r["parts"] / (r["run"] * ideal[mid]) if r["run"] else 0
        quality = (r["parts"] - r["defects"]) / r["parts"] if r["parts"] else 0
        rows.append({
            "machine_id": mid,
            "availability": round(availability, 3),
            "performance": round(min(perf, 1.0), 3),
            "quality": round(quality, 3),
            "oee": round(availability * min(perf, 1.0) * quality, 3),
            "parts_produced": r["parts"],
            "defects": r["defects"],
        })
    rows.sort(key=lambda x: x["oee"])

    downtime_per_machine = list(db.shift_logs.aggregate([
        {"$match": {"date": {"$gte": D90}}},
        {"$group": {"_id": "$machine_id",
                    "downtime_90d": {"$sum": "$downtime_hours"}}},
        {"$sort": {"downtime_90d": -1}},
    ]))
    downtime_per_machine = [
        {"machine_id": r["_id"], "downtime_90d": round(r["downtime_90d"], 1)}
        for r in downtime_per_machine
    ]
    by_cause = list(db.breakdowns.aggregate([
        {"$match": {"date": {"$gte": D90}}},
        {"$group": {"_id": "$cause",
                    "downtime_hours": {"$sum": "$downtime_hours"},
                    "events": {"$sum": 1},
                    "cost_rs": {"$sum": "$repair_cost_rs"}}},
        {"$sort": {"downtime_hours": -1}},
    ]))
    avg_oee = round(sum(r["oee"] for r in rows) / len(rows), 3) if rows else 0
    return {
        "per_machine": rows,
        "downtime_per_machine": downtime_per_machine,
        "downtime_by_cause": by_cause,
        "avg_oee": avg_oee,
    }


# ----------------------------------------------------------------- M5 tools
def m5_tools(db):
    by_type = list(db.tool_changes.aggregate([
        {"$group": {"_id": "$tool_type",
                    "avg_life_used_pct": {"$avg": "$life_used_pct"},
                    "changes": {"$sum": 1}}},
        {"$sort": {"avg_life_used_pct": 1}},
    ]))
    # early failures: tools changed before using 70% of rated life in last 30 days
    early = list(db.tool_changes.aggregate([
        {"$match": {"date": {"$gte": D30}, "life_used_pct": {"$lt": 70}}},
        {"$group": {"_id": {"machine": "$machine_id", "type": "$tool_type"},
                    "early_failures": {"$sum": 1},
                    "avg_life_pct": {"$avg": "$life_used_pct"}}},
        {"$sort": {"early_failures": -1}},
        {"$limit": 10},
    ]))
    early = [{"machine_id": e["_id"]["machine"], "tool_type": e["_id"]["type"],
              "early_failures": e["early_failures"],
              "avg_life_pct": round(e["avg_life_pct"], 1)} for e in early]
    per_machine = list(db.tool_changes.aggregate([
        {"$match": {"date": {"$gte": D90}}},
        {"$group": {"_id": "$machine_id",
                    "avg_life_used_pct": {"$avg": "$life_used_pct"},
                    "changes": {"$sum": 1}}},
        {"$sort": {"avg_life_used_pct": 1}},
    ]))
    alerts = [t for t in by_type if t["avg_life_used_pct"] < 85]
    return {
        "by_type": [{"tool_type": t["_id"],
                     "avg_life_used_pct": round(t["avg_life_used_pct"], 1),
                     "changes": t["changes"]} for t in by_type],
        "early_failures": early,
        "per_machine": [{"machine_id": t["_id"],
                         "avg_life_used_pct": round(t["avg_life_used_pct"], 1),
                         "changes": t["changes"]} for t in per_machine],
        "alerts": [{"tool_type": t["_id"],
                    "avg_life_used_pct": round(t["avg_life_used_pct"], 1),
                    "message": f"{t['_id']} averaging only "
                               f"{round(t['avg_life_used_pct'], 1)}% of rated life — "
                               "check supplier quality or cutting parameters"}
                   for t in alerts],
    }


def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    print("Running analytics pipelines...")
    safety = m1_safety(db);      save("safety.json", safety)
    maint = m2_maintenance(db);  save("maintenance.json", maint)
    oee = m4_oee(db);            save("oee.json", oee)
    risk = m3_risk(db, safety, maint, oee); save("risk.json", risk)
    tools = m5_tools(db);        save("tools.json", tools)

    summary = {
        "generated_at": str(NOW),
        "total_documents": sum(db[c].count_documents({}) for c in db.list_collection_names()),
        "total_violations_90d": safety["total_violations_90d"],
        "overdue_machines": len(maint["overdue"]),
        "due_soon_machines": len(maint["due_soon"]),
        "red_machines": [m["machine_id"] for m in risk["red"]],
        "avg_oee_30d": oee["avg_oee"],
        "top_downtime_cause": oee["downtime_by_cause"][0]["_id"]
        if oee["downtime_by_cause"] else None,
        "tool_alerts": len(tools["alerts"]),
    }
    save("summary.json", summary)
    print("All 5 modules complete.")


if __name__ == "__main__":
    main()
