"""
Smart Factory Health & Safety Analytics System
Data generator — creates realistic factory log data and loads it into MongoDB.

Collections:
  machines        - 25 CNC/VMC/lathe/drill/press machines
  operators       - 40 operators across 3 shifts
  safety_checks   - daily safety checklist per machine per shift (~27k docs)
  maintenance     - service history per machine
  breakdowns      - unplanned breakdown events (~2k docs)
  shift_logs      - production log per machine per shift (~27k docs)
  tool_changes    - cutting tool change records (~6k docs)

Total: ~62,000 documents (big-data scale for the analytics pipelines).

Run:  python data/generate_data.py
"""
import random
from datetime import datetime, timedelta, date

from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "factory_db"
DAYS = 365
SEED = 42

random.seed(SEED)

# ---------------------------------------------------------------- machines
MACHINE_TYPES = [
    ("CNC Lathe", 8, 22),   # (type, count, ideal parts/hour)
    ("VMC", 8, 18),
    ("Drilling", 4, 45),
    ("Power Press", 3, 60),
    ("Grinding", 2, 30),
]

SHIFTS = ["A", "B", "C"]

# machines that are deliberately "problem machines" so analytics show a story
BAD_MACHINES = {"M-003", "M-011", "M-019"}        # high safety violations + breakdowns
BAD_OPERATORS = {"O-005", "O-014", "O-023", "O-031", "O-038"}

SAFETY_ITEMS = [
    "ppe_worn",
    "chuck_guard_closed",
    "emergency_stop_tested",
    "lockout_tagout_done",
    "coolant_level_ok",
    "floor_area_clear",
]

BREAKDOWN_CAUSES = [
    "Spindle bearing failure",
    "Tool crash",
    "Coolant pump failure",
    "Electrical panel fault",
    "Hydraulic leak",
    "Chuck jaw damage",
    "Servo motor fault",
    "Belt breakage",
]

TOOL_TYPES = {
    "Carbide Insert": (800, 1200),
    "End Mill": (400, 700),
    "Drill Bit": (600, 1000),
    "Tap": (300, 500),
}


def gen_machines():
    machines = []
    n = 1
    for mtype, count, ideal_rate in MACHINE_TYPES:
        for _ in range(count):
            mid = f"M-{n:03d}"
            machines.append({
                "machine_id": mid,
                "type": mtype,
                "ideal_parts_per_hour": ideal_rate,
                "install_year": random.randint(2012, 2022),
                "criticality": random.choice(["high", "high", "medium", "medium", "low"]),
                "service_interval_hours": 500,
            })
            n += 1
    return machines


def gen_operators():
    first = ["Ramesh", "Suresh", "Amit", "Vijay", "Prakash", "Mohan", "Dinesh",
             "Kiran", "Sanjay", "Ravi", "Anil", "Manoj", "Deepak", "Naresh", "Harish"]
    last = ["Patel", "Sharma", "Gupta", "Yadav", "Singh", "Kumar", "Mehta",
            "Joshi", "Rana", "Chauhan", "Thakor", "Desai", "Prajapati", "Solanki"]
    ops = []
    for i in range(1, 41):
        ops.append({
            "operator_id": f"O-{i:03d}",
            "name": f"{random.choice(first)} {random.choice(last)}",
            "experience_years": random.randint(1, 18),
            "shift": SHIFTS[(i - 1) % 3],
        })
    return ops


def fail_prob(machine_id, operator_id):
    p = 0.05
    if machine_id in BAD_MACHINES:
        p += 0.28
    if operator_id in BAD_OPERATORS:
        p += 0.15
    return min(p, 0.6)


def gen_safety_checks(machines, operators):
    """One safety checklist per machine per shift per day."""
    ops_by_shift = {s: [o for o in operators if o["shift"] == s] for s in SHIFTS}
    docs = []
    today = date.today()
    for d in range(DAYS):
        day = today - timedelta(days=DAYS - d)
        for m in machines:
            for shift in SHIFTS:
                op = random.choice(ops_by_shift[shift])
                p = fail_prob(m["machine_id"], op["operator_id"])
                checks = {}
                for item in SAFETY_ITEMS:
                    # emergency stop test fails a bit more often everywhere
                    ip = p + 0.03 if item == "emergency_stop_tested" else p
                    checks[item] = "fail" if random.random() < ip else "pass"
                violations = sum(1 for v in checks.values() if v == "fail")
                docs.append({
                    "machine_id": m["machine_id"],
                    "operator_id": op["operator_id"],
                    "shift": shift,
                    "date": datetime(day.year, day.month, day.day),
                    "checks": checks,
                    "violations": violations,
                })
    return docs


def gen_maintenance(machines):
    """Service history; tracks next due runtime hours per machine."""
    docs = []
    for m in machines:
        runtime = 0.0
        day_offset = random.randint(200, 340)
        n_services = random.randint(8, 14)
        for _ in range(n_services):
            runtime += random.uniform(350, 550)
            svc_date = date.today() - timedelta(days=day_offset)
            docs.append({
                "machine_id": m["machine_id"],
                "service_date": datetime(svc_date.year, svc_date.month, svc_date.day),
                "service_type": "preventive" if random.random() > 0.25 else "breakdown_repair",
                "runtime_hours_at_service": round(runtime, 1),
                "next_due_hours": round(runtime + m["service_interval_hours"], 1),
                "technician": f"T-{random.randint(1, 8):02d}",
                "cost_rs": random.randint(2000, 25000),
            })
            day_offset -= random.randint(20, 45)
            if day_offset < 0:
                break
        # store current runtime on the machine doc for due-date maths
        # (some machines run past their service interval -> overdue demo data)
        m["current_runtime_hours"] = round(runtime + random.uniform(100, 620), 1)
    return docs


def gen_breakdowns(machines):
    docs = []
    today = date.today()
    for m in machines:
        base = 26 if m["machine_id"] in BAD_MACHINES else random.randint(4, 12)
        for _ in range(base):
            day = today - timedelta(days=random.randint(0, DAYS - 1))
            downtime = round(random.uniform(0.5, 14), 1)
            if m["machine_id"] in BAD_MACHINES and random.random() < 0.4:
                downtime = round(random.uniform(8, 24), 1)
            docs.append({
                "machine_id": m["machine_id"],
                "date": datetime(day.year, day.month, day.day),
                "shift": random.choice(SHIFTS),
                "downtime_hours": downtime,
                "cause": random.choice(BREAKDOWN_CAUSES),
                "repair_cost_rs": int(downtime * random.randint(1500, 4000)),
            })
    return docs


def gen_shift_logs(machines):
    """Production log per machine per shift per day — feeds OEE."""
    docs = []
    today = date.today()
    for d in range(DAYS):
        day = today - timedelta(days=DAYS - d)
        for m in machines:
            for shift in SHIFTS:
                planned = 8.0
                avail_factor = random.uniform(0.82, 0.97)
                if m["machine_id"] in BAD_MACHINES:
                    avail_factor = random.uniform(0.60, 0.85)
                run_hours = round(planned * avail_factor, 2)
                downtime = round(planned - run_hours, 2)
                ideal = m["ideal_parts_per_hour"]
                parts = int(run_hours * ideal * random.uniform(0.85, 1.0))
                defect_rate = random.uniform(0.01, 0.04)
                if m["machine_id"] in BAD_MACHINES:
                    defect_rate = random.uniform(0.05, 0.12)
                defects = int(parts * defect_rate)
                docs.append({
                    "machine_id": m["machine_id"],
                    "shift": shift,
                    "date": datetime(day.year, day.month, day.day),
                    "planned_hours": planned,
                    "run_hours": run_hours,
                    "downtime_hours": downtime,
                    "parts_produced": parts,
                    "defects": defects,
                })
    return docs


def gen_tool_changes(machines):
    docs = []
    today = date.today()
    tid = 1
    for m in machines:
        n = random.randint(180, 280)
        for _ in range(n):
            ttype, (lo, hi) = random.choice(list(TOOL_TYPES.items()))
            rated = random.randint(lo, hi)
            # bad machines chew through tools faster
            life_factor = random.uniform(0.55, 0.95) if m["machine_id"] in BAD_MACHINES \
                else random.uniform(0.85, 1.15)
            if ttype == "Tap":
                life_factor *= 0.78  # cheap supplier batch -> wears out early
            parts = int(rated * life_factor)
            day = today - timedelta(days=random.randint(0, DAYS - 1))
            docs.append({
                "tool_id": f"T-{tid:05d}",
                "machine_id": m["machine_id"],
                "tool_type": ttype,
                "date": datetime(day.year, day.month, day.day),
                "parts_produced": parts,
                "rated_life_parts": rated,
                "life_used_pct": round(parts / rated * 100, 1),
            })
            tid += 1
    return docs


def main():
    print("Generating factory data...")
    machines = gen_machines()
    operators = gen_operators()
    safety = gen_safety_checks(machines, operators)
    maintenance = gen_maintenance(machines)
    breakdowns = gen_breakdowns(machines)
    shift_logs = gen_shift_logs(machines)
    tools = gen_tool_changes(machines)

    print(f"  machines:      {len(machines)}")
    print(f"  operators:     {len(operators)}")
    print(f"  safety_checks: {len(safety)}")
    print(f"  maintenance:   {len(maintenance)}")
    print(f"  breakdowns:    {len(breakdowns)}")
    print(f"  shift_logs:    {len(shift_logs)}")
    print(f"  tool_changes:  {len(tools)}")
    total = sum([len(machines), len(operators), len(safety), len(maintenance),
                 len(breakdowns), len(shift_logs), len(tools)])
    print(f"  TOTAL:         {total} documents")

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    for name in ["machines", "operators", "safety_checks", "maintenance",
                 "breakdowns", "shift_logs", "tool_changes"]:
        db[name].drop()
    db["machines"].insert_many(machines)
    db["operators"].insert_many(operators)
    # bulk insert in chunks to stay under BSON limits
    for coll_name, docs in [("safety_checks", safety), ("maintenance", maintenance),
                            ("breakdowns", breakdowns), ("shift_logs", shift_logs),
                            ("tool_changes", tools)]:
        for i in range(0, len(docs), 5000):
            db[coll_name].insert_many(docs[i:i + 5000])
        print(f"  inserted {coll_name}: {len(docs)}")
    print(f"\nDone. Database '{DB_NAME}' ready with {total} documents.")


if __name__ == "__main__":
    main()
