"""Benchmark the existing solver adapters; writes only docs/data artifacts."""
import argparse
import csv
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "algorithms")]
METHODS = ["Backtracking", "A*", "Genetic Algorithm"]
CASES = [
    {"id": "ce-open", "label": "Civil Engineering · Year 1 · Sem 1", "program": "BSCE",
     "specialization": "GENERAL", "year": "1st year", "semester": "1st Semester", "blocked": []},
    {"id": "ce-blocked", "label": "Civil Engineering · With unavailable hours", "program": "BSCE",
     "specialization": "GENERAL", "year": "1st year", "semester": "1st Semester",
     "blocked": [[day, slot] for day in [0, 2, 4] for slot in range(2, 6)]},
    {"id": "me-senior", "label": "Mechanical Engineering · Year 4 · Sem 2", "program": "BSME",
     "specialization": "GENERAL", "year": "4th year", "semester": "2nd Semester", "blocked": []},
    {"id": "ce-gap30", "label": "Civil Engineering · 30-minute target gap", "program": "BSCE",
     "specialization": "GENERAL", "year": "1st year", "semester": "1st Semester", "gap_minutes": 30, "blocked": []},
    {"id": "ce-gap60", "label": "Civil Engineering · 60-minute target gap", "program": "BSCE",
     "specialization": "GENERAL", "year": "1st year", "semester": "1st Semester", "gap_minutes": 60, "blocked": []},
    {"id": "ce-gap120-blocked", "label": "Civil Engineering · 120-minute gap + unavailable hours", "program": "BSCE",
     "specialization": "GENERAL", "year": "1st year", "semester": "1st Semester", "gap_minutes": 120,
     "blocked": [[day, slot] for day in [0, 2, 4] for slot in range(2, 6)]},
]


def gap_metrics(sections, target):
    by_day = {}
    for section in sections:
        for day, start, end in section["meetings"]:
            by_day.setdefault(day, []).append((start, end))
    gaps = []
    for intervals in by_day.values():
        intervals.sort()
        previous_end = intervals[0][1]
        for start, end in intervals[1:]:
            if start >= previous_end:
                gaps.append(start - previous_end)
            previous_end = max(previous_end, end)
    return {"average_gap": statistics.mean(gaps) if gaps else None,
            "gap_target_error": statistics.mean(abs(gap - target) for gap in gaps) if gaps and target else None}


def worker(case, method, seed, generations, population):
    import helper
    import genetic_algorithm as ga
    from algorithms.solvers import run_solver, blocked_tuples
    helper.DATA_DIR = str(ROOT / "filtered")
    ga.MAXIMUM_GENERATION, ga.POPULATION_SIZE = generations, population
    random.seed(seed)
    blocked = {tuple(pair) for pair in case["blocked"]}
    info = SimpleNamespace(course=case["program"], specialization=case["specialization"],
                           year=case["year"], semester=case["semester"],
                           gap=case.get("gap_minutes", 0) / 60, algorithm=method)
    row = {"case": case["id"], "method": method, "seed": seed,
           "target_gap_minutes": case.get("gap_minutes", 0)}
    start = time.perf_counter()
    try:
        result = run_solver(info, blocked, str(ROOT / "filtered"))
    except Exception as error:
        row.update(status="error" if type(error).__name__ != "SolverMessage" else "no_schedule",
                   runtime_sec=time.perf_counter() - start, valid=False,
                   message=str(error), schedule=[])
        return row
    row["runtime_sec"] = time.perf_counter() - start
    required, specialized, elective, ge, _ = helper.load_term_data(
        info.course, info.specialization, info.year, info.semester)
    units = {r["course_code"]: helper.parse_number(r["units"]) or 0
             for r in required + specialized + elective + ge}
    sections = [{"course_code": s.course, "section": s.section,
                 "meetings": [("M T W Th F S".split()[d], m.start, m.end)
                              for m in s.meetings for d in m.days]}
                for s in result.sections]
    blocks = [(day, helper.to_minutes(start), helper.to_minutes(end))
              for day, start, end in blocked_tuples(blocked)]
    metrics = helper.evaluate_schedule(sections, units, {r["course_code"] for r in required},
                                      blocks, max_non_academic_units=helper.MAX_NON_ACADEMIC_UNITS)
    row.update(metrics, **gap_metrics(sections, case.get("gap_minutes", 0)),
               status="returned", fitness=helper.fitness_from_metrics(metrics),
               nodes=result.nodes_expanded, node_limit_reached=result.node_limit_reached,
               schedule=sections, required_count=len({r["course_code"] for r in required}))
    return row


def summarize(rows):
    summaries = []
    for case in CASES:
        for method in METHODS:
            group = [r for r in rows if r["case"] == case["id"] and r["method"] == method]
            valid = [r for r in group if r["valid"]]
            item = {"case": case["id"], "method": method, "runs": len(group),
                    "valid_runs": len(valid), "success_pct": 100 * len(valid) / len(group),
                    "timeouts": sum(r["status"] == "timeout" for r in group),
                    "median_runtime": statistics.median(r["runtime_sec"] for r in group)}
            for metric in ["fitness", "academic_units", "gap_minutes", "blocked_count", "average_gap", "gap_target_error"]:
                values = [r[metric] for r in valid if r[metric] is not None]
                item[metric] = statistics.median(values) if values else None
            summaries.append(item)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generations", type=int, default=1000)
    parser.add_argument("--population", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--worker", nargs=3, metavar=("CASE", "METHOD", "SEED"))
    args = parser.parse_args()
    if min(args.generations, args.repeats, args.timeout) <= 0 or args.population < 3:
        parser.error("positive generations/repeats/timeout and population >= 3 required")
    if args.worker:
        case_id, method, seed = args.worker
        print(json.dumps(worker(next(c for c in CASES if c["id"] == case_id), method,
                                int(seed), args.generations, args.population)))
        return
    rows = []
    for case in CASES:
        for method in METHODS:
            for seed in range(args.repeats):
                command = [sys.executable, str(Path(__file__).resolve()), "--generations", str(args.generations),
                           "--population", str(args.population), "--worker", case["id"], method, str(seed)]
                try:
                    completed = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout,
                                               check=True, cwd=ROOT, env={**os.environ, "PYTHONHASHSEED": "0",
                                                                        "PYTHONDONTWRITEBYTECODE": "1"})
                    row = json.loads(completed.stdout)
                except subprocess.TimeoutExpired:
                    row = dict(case=case["id"], method=method, seed=seed, status="timeout",
                               target_gap_minutes=case.get("gap_minutes", 0),
                               runtime_sec=args.timeout, valid=False, message="Wall-clock limit reached", schedule=[])
                rows.append(row)
                print(f"{case['id']:12} {method:18} seed={seed} {row['status']:12} "
                      f"{row['runtime_sec']:.3f}s valid={row['valid']}", flush=True)
    inputs = [*sorted((ROOT / "filtered").glob("*.csv")),
              *sorted((ROOT / "algorithms").glob("*.py")), ROOT / "schedule_model.py", Path(__file__).resolve()]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {"python": platform.python_version(), "os": platform.system(),
                        "machine": platform.machine(), "processor": platform.processor()},
        "config": {"generations": args.generations, "population": args.population, "mutation_rate": 0.2,
                   "repeats": args.repeats, "timeout_sec": args.timeout, "node_limit": 100000, "hash_seed": 0,
                   "profile": "quick" if (args.generations, args.population) != (1000, 100) else "default"},
        "sha256": {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
        "cases": CASES, "methods": METHODS, "runs": rows, "summary": summarize(rows)}
    output = ROOT / "docs" / "data"
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    columns = ["case", "method", "seed", "status", "runtime_sec", "valid", "fitness", "academic_units",
               "non_academic_units", "conflicts", "missing_required", "excess_units", "gap_minutes",
               "blocked_count", "target_gap_minutes", "average_gap", "gap_target_error",
               "nodes", "node_limit_reached", "message"]
    with (output / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    assert len(rows) == len(CASES) * len(METHODS) * args.repeats
    assert all(r["runtime_sec"] >= 0 for r in rows)
    assert all(not r["valid"] or (r["conflicts"] == r["missing_required"] == r["excess_units"] == 0) for r in rows)
    print("Saved docs/data/results.json and results.csv")


if __name__ == "__main__":
    main()
