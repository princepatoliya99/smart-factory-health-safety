"""
Creates indexes on all collections — this is the "big data" performance part.
Without indexes, the aggregation pipelines scan ~60k docs every run;
with them, dashboard queries return in milliseconds.

Run:  python mongo/setup.py
"""
from pymongo import MongoClient, ASCENDING

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "factory_db"

INDEXES = {
    "machines": [("machine_id", ASCENDING)],
    "operators": [("operator_id", ASCENDING)],
    "safety_checks": [
        ("machine_id", ASCENDING), ("date", ASCENDING),
        ("operator_id", ASCENDING), ("shift", ASCENDING),
    ],
    "maintenance": [("machine_id", ASCENDING), ("service_date", ASCENDING)],
    "breakdowns": [("machine_id", ASCENDING), ("date", ASCENDING), ("cause", ASCENDING)],
    "shift_logs": [("machine_id", ASCENDING), ("date", ASCENDING), ("shift", ASCENDING)],
    "tool_changes": [("machine_id", ASCENDING), ("tool_type", ASCENDING), ("date", ASCENDING)],
}


def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    for coll, fields in INDEXES.items():
        for field, direction in fields:
            name = f"{field}_{direction}"
            try:
                db[coll].create_index([(field, direction)], name=name)
                print(f"  {coll}: index on {field}")
            except Exception as e:
                print(f"  {coll}: {field} -> {e}")
    print("Indexes ready.")


if __name__ == "__main__":
    main()
