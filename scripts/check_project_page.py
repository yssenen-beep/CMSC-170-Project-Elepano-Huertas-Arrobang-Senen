"""Check local page links and independently recompute published measurements."""
import csv
import hashlib
import json
import math
import statistics
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "algorithms"))
import helper
from benchmark import gap_metrics


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.refs = set(), []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            assert attrs["id"] not in self.ids, f"Duplicate ID: {attrs['id']}"
            self.ids.add(attrs["id"])
        self.refs.extend(attrs[k] for k in ("src", "href") if k in attrs)


def main():
    sample = [{"meetings": [("M", 480, 540), ("M", 540, 600), ("M", 660, 720)]}]
    assert gap_metrics(sample, 30) == {"average_gap": 30, "gap_target_error": 30}
    assert gap_metrics(sample, 0) == {"average_gap": 30, "gap_target_error": None}
    assert gap_metrics([{"meetings": [("M", 480, 540)]}], 60) == {"average_gap": None, "gap_target_error": None}
    docs = ROOT / "docs"
    page = Page()
    page.feed((docs / "index.html").read_text(encoding="utf-8"))
    for ref in page.refs:
        url = urlsplit(ref)
        if url.scheme or url.netloc:
            continue
        if url.path:
            assert (docs / unquote(url.path)).is_file(), f"Missing linked file: {ref}"
        elif url.fragment:
            assert url.fragment in page.ids, f"Missing anchor: {ref}"
    data = json.loads((docs / "data/results.json").read_text(encoding="utf-8"))
    with (docs / "data/results.csv").open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == len(data["runs"]) == len(data["cases"]) * len(data["methods"]) * data["config"]["repeats"]
    for name, digest in data["sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, f"Stale benchmark input: {name}"
    helper.DATA_DIR = str(ROOT / "filtered")
    for case in data["cases"]:
        required, spec, elective, ge, offerings = helper.load_term_data(case["program"], case["specialization"], case["year"], case["semester"])
        units = {r["course_code"]: helper.parse_number(r["units"]) or 0 for r in required + spec + elective + ge}
        days = ["M", "T", "W", "Th", "F", "S"]
        blocked = [(days[day], 420 + slot * 30, 450 + slot * 30) for day, slot in case["blocked"]]
        for method in data["methods"]:
            group = [r for r in data["runs"] if r["case"] == case["id"] and r["method"] == method]
            assert sorted(r["seed"] for r in group) == list(range(data["config"]["repeats"]))
            for row in group:
                assert row["runtime_sec"] >= 0
                assert row["target_gap_minutes"] == case.get("gap_minutes", 0)
                if row["status"] != "returned":
                    assert not row["valid"]
                    continue
                for section in row["schedule"]:
                    assert any(s["course_code"] == section["course_code"] and s["section"] == section["section"]
                               and set(map(tuple, s["meetings"])) == set(map(tuple, section["meetings"]))
                               for s in offerings), f"Returned section not in offerings: {section}"
                metrics = helper.evaluate_schedule(row["schedule"], units, {r["course_code"] for r in required},
                                                  blocked, max_non_academic_units=5)
                for key, expected in metrics.items():
                    assert row[key] == expected, (case["id"], method, key)
                assert math.isclose(row["fitness"], helper.fitness_from_metrics(metrics))
                by_day = {}
                for section in row["schedule"]:
                    for day, start, end in section["meetings"]:
                        by_day.setdefault(day, []).append((start, end))
                if row["valid"]:
                    gaps = [following[0] - previous[1] for intervals in by_day.values()
                            for previous, following in zip(sorted(intervals), sorted(intervals)[1:])]
                    assert row["average_gap"] == (statistics.mean(gaps) if gaps else None)
                    target = case.get("gap_minutes", 0)
                    expected_error = statistics.mean(abs(gap - target) for gap in gaps) if gaps and target else None
                    assert row["gap_target_error"] == expected_error
            valid = [r for r in group if r["valid"]]
            summary = next(s for s in data["summary"] if s["case"] == case["id"] and s["method"] == method)
            assert summary["valid_runs"] == len(valid)
            assert summary["success_pct"] == 100 * len(valid) / len(group)
            assert summary["median_runtime"] == statistics.median(r["runtime_sec"] for r in group)
            for metric in ("fitness", "academic_units", "gap_minutes", "blocked_count"):
                assert summary[metric] == (statistics.median(r[metric] for r in valid) if valid else None)
            for metric in ("average_gap", "gap_target_error"):
                values = [r[metric] for r in valid if r[metric] is not None]
                assert summary[metric] == (statistics.median(values) if values else None)
    for exported, row in zip(csv_rows, data["runs"]):
        for key in exported:
            expected = row.get(key)
            assert exported[key] == ("" if expected is None else str(expected)), f"CSV/JSON mismatch: {key}"
    print(f"PASS: local links, input hashes, {len(data['runs'])} run evaluations, summary medians, and CSV/JSON agreement")


if __name__ == "__main__":
    main()
