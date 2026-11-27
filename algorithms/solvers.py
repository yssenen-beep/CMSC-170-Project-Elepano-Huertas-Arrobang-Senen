import contextlib
import csv
import importlib
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(HERE), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from schedule_model import (
    DAY_LABELS, DAY_START_MIN, SLOT_MIN,
    Meeting, ScheduledSection, ScheduleResult, fmt_time, result_from_text,
)

try:                                     
    from schedule_model import SolverMessage
except ImportError:
    class SolverMessage(Exception):
        """Friendly error text shown to the user."""

CURRICULUM_FILE = "ceat_program_courses.csv"

def find_data_dir() -> str:
    seen = set()
    for base in (ROOT, HERE, Path.cwd()):
        candidates = [base]
        try:
            for child in sorted(base.iterdir()):
                if child.is_dir() and not child.name.startswith((".", "__")):
                    candidates.append(child)
                    candidates.extend(sorted(c for c in child.iterdir() if c.is_dir()))
        except OSError:
            pass
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if (resolved / CURRICULUM_FILE).is_file():
                return str(resolved)
    return ""


def load_curriculum(data_dir: str) -> dict:
    if not data_dir:
        return {}
    path = Path(data_dir) / CURRICULUM_FILE
    if not path.is_file():
        return {}
    programs = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            program = row.get("program") or ""
            spec = row.get("specialization") or ""
            if program.strip() and spec.strip():
                programs.setdefault(program, set()).add(spec)
    return {
        p: sorted(specs, key=str.casefold)
        for p, specs in sorted(programs.items(), key=lambda kv: kv[0].casefold())
    }

def blocked_tuples(blocked):
    out = []
    for day, slot in sorted(blocked):
        start = DAY_START_MIN + slot * SLOT_MIN
        out.append((DAY_LABELS[day], fmt_time(start), fmt_time(start + SLOT_MIN)))
    return out


def blocked_periods(blocked):
    by_day = {}
    for day, slot in blocked:
        by_day.setdefault(day, []).append(slot)
    periods = []
    for day, slots in sorted(by_day.items()):
        slots.sort()
        run_start = prev = slots[0]
        for s in slots[1:] + [None]:
            if s is not None and s == prev + 1:
                prev = s
                continue
            periods.append({
                "days": {DAY_LABELS[day]},
                "window": (DAY_START_MIN + run_start * SLOT_MIN,
                           DAY_START_MIN + (prev + 1) * SLOT_MIN),
            })
            if s is not None:
                run_start = prev = s
    return periods


def _leading_int(text: str) -> int:
    return int(re.match(r"\d+", text).group())


def _prepare(module_name: str, data_dir: str):
    import helper
    helper.DATA_DIR = data_dir
    if not data_dir or not (Path(data_dir) / CURRICULUM_FILE).is_file():
        raise SolverMessage(
            f"Could not find {CURRICULUM_FILE} in the data folder:\n"
            f"{data_dir or '(no folder selected)'}\n\n"
            "Pick the folder that holds the CSV files using Browse...")
    try:
        return importlib.import_module(module_name)
    except ImportError as e:
        raise SolverMessage(
            f"Could not load {module_name}.py.\n"
            f"Keep it in the Algorithms folder ({HERE}).\n\n{e}")


def _run_printing_solver(func, *args) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        func(*args)
    return buffer.getvalue()


def _message_from(output: str) -> str:
    lines = [ln for ln in output.splitlines()
             if ln.strip() and ln.strip().lower() != "solving timetable..."]
    return "\n".join(lines) or "No valid schedule was found."


def _astar(info, blocked, data_dir) -> ScheduleResult:
    mod = _prepare("astar_scheduler", data_dir)
    gap_min = int(round(info.gap * 60)) if info.gap > 0 else 0
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        mod.a_star(
            info.course, info.specialization, info.year, info.semester,
            blocked_tuples(blocked),
            preferred_gap=gap_min,
        )
    out = buffer.getvalue()
    result = result_from_text(out)
    if not result.sections:
        raise SolverMessage(_message_from(out))
    result.extra = {
        "Node limit": f"{mod.MAXIMUM_NODES:,}",
        "Target gap": f"{gap_min} min" if gap_min else "0 min (minimize gaps)",
    }
    return result


def _genetic(info, blocked, data_dir) -> ScheduleResult:
    mod = _prepare("genetic_algorithm", data_dir)
    out = _run_printing_solver(
        mod.genetic_algorithm, info.course, info.specialization, info.year, info.semester,
        blocked_tuples(blocked))
    result = result_from_text(out)
    if not result.sections:
        raise SolverMessage(_message_from(out))
    result.extra = {
        "Max generations": f"{mod.MAXIMUM_GENERATION:,}",
        "Population size": mod.POPULATION_SIZE,
        "Mutation rate": mod.MUTATION_RATE,
    }
    return result


def _group_meetings(tuples):
    groups = {}
    for day, start, end in tuples:
        if day in DAY_LABELS:                       # skips Sunday, which the grid doesn't show
            groups.setdefault((start, end), []).append(DAY_LABELS.index(day))
    return [Meeting(sorted(days), s, e) for (s, e), days in groups.items()]


def _backtracking(info, blocked, data_dir) -> ScheduleResult:
    bt = _prepare("backtracking_scheduler", data_dir)
    year, semester = _leading_int(info.year), _leading_int(info.semester)

    try:
        courses, offerings, _invalid = bt.load_courses_and_offerings(
            info.course, info.specialization, year, semester)
    except FileNotFoundError as e:
        raise SolverMessage(f"Could not find the class schedule file:\n{e.filename or e}")
    if not courses:
        raise SolverMessage("No courses were found for that program, year, and semester.")

    missing = [c["course_code"] for c in courses
               if not offerings.get(bt.normalize(c["course_code"]))]
    if missing:
        raise SolverMessage("No section offerings were found for these plan courses:\n  - "
                            + "\n  - ".join(missing)
                            + "\nA complete schedule cannot be built from the current data.")

    gap_minutes = int(round(info.gap * 60)) if info.gap > 0 else None   # 0 = no preference
    prefs = {"blocked_periods": blocked_periods(blocked), "gap": gap_minutes}

    best, _best_score, nodes, limit_reached = bt.search_schedule(courses, offerings, prefs)
    if best is None:
        if limit_reached:
            raise SolverMessage(f"No viable schedule was found within the "
                                f"{bt.SEARCH_NODE_LIMIT:,}-node search limit.")
        raise SolverMessage("No schedule satisfies the time-conflict and unit constraints "
                            f"({bt.MAX_ACADEMIC_UNITS} academic, "
                            f"{bt.MAX_NON_ACADEMIC_UNITS} non-academic units).")

    sections, non_academic = [], 0.0
    for course, option in sorted(best, key=lambda co: co[0]["course_code"]):
        units = bt.get_course_units(course, option) or 0
        non_acad = bt.is_non_academic_course(course)
        if non_acad:
            non_academic += units
        sections.append(ScheduledSection(
            course=course["course_code"],
            section=option["section"] or "(unlabeled)",
            units=units,
            meetings=_group_meetings(option["meetings"]),
            hk=non_acad,
            time_text=option["time_slot"] or "TBA / no fixed time",
        ))

    scores = bt.score_schedule(best, prefs)
    extra = {
        "Node limit": f"{bt.SEARCH_NODE_LIMIT:,}",
        "Target gap": f"{gap_minutes} min" if gap_minutes is not None else "none",
        "Non-academic units": f"{non_academic:g} / {bt.MAX_NON_ACADEMIC_UNITS}",
    }
    if scores["overall"] is None:
        extra["Fitness"] = "n/a (no blocked times or gap set)"
    else:
        extra["Fitness scale"] = "0-100 preference score"
    for key, label in (("blocked_time", "Blocked-time fit"), ("gap", "Gap score")):
        if key in scores["components"]:
            extra[label] = f"{scores['components'][key]:.1f} / 100"

    return ScheduleResult(
        sections=sections,
        max_units=bt.MAX_ACADEMIC_UNITS,
        fitness=scores["overall"],
        nodes_expanded=nodes,
        node_limit_reached=limit_reached,
        extra=extra,
    )


RUNNERS = {
    "Backtracking": _backtracking,
    "A*": _astar,
    "Genetic Algorithm": _genetic,
}


def run_solver(information, blocked, data_dir: str) -> ScheduleResult:
    runner = RUNNERS.get(information.algorithm)
    if runner is None:
        raise SolverMessage(f"Unknown algorithm: {information.algorithm}")
    return runner(information, blocked, data_dir)
