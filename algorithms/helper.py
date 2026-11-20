import csv
import re
from itertools import combinations
from pathlib import Path

MAX_UNITS = 21                  
MAX_NON_ACADEMIC_UNITS = 5      
SEARCH_NODE_LIMIT = 100_000
HARD_CONSTRAINT_WEIGHT = 1000
SOFT_CONSTRAINT_WEIGHT = 0.01

YEAR_MAP = {"1st year": "1", "2nd year": "2", "3rd year": "3", "4th year": "4"}
SEMESTER_MAP = {"1st Semester": "1", "2nd Semester": "2"}
SEMESTER_FILES = {
    "1": "ceat_class_schedule_1st_sem.csv",
    "2": "ceat_class_schedule_2nd_sem.csv",
}
CURRICULUM_FILENAME = "ceat_program_courses.csv"
DATA_DIR = None

DAY_ALIASES = {
    "m": "M", "mon": "M", "monday": "M",
    "t": "T", "tu": "T", "tue": "T", "tues": "T", "tuesday": "T",
    "w": "W", "wed": "W", "wednesday": "W",
    "th": "Th", "r": "Th", "thu": "Th", "thur": "Th", "thurs": "Th", "thursday": "Th",
    "f": "F", "fri": "F", "friday": "F",
    "s": "S", "sa": "S", "sat": "S", "saturday": "S",
    "su": "Su", "sun": "Su", "sunday": "Su",
}
DAY_ORDER = {"M": 0, "T": 1, "W": 2, "Th": 3, "F": 4, "S": 5, "Su": 6}
NON_ACADEMIC_PREFIXES = ("HK","NSTP")

_MEETING_RE = re.compile(r"^\s*(.*?)\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*$")


def normalize(value):
    return " ".join((value or "").strip().upper().split())


def parse_integer(value):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def parse_number(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def is_non_academic_course(course_code, prefixes=("HK", "NSTP")):
    parts = normalize(course_code).split(maxsplit=1)
    return bool(parts) and parts[0] in prefixes


def to_minutes(value):
    text = (value or "").strip().upper()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?:\s*(AM|PM))?", text)
    if not match:
        return None
    hour, minute, period = int(match.group(1)), int(match.group(2)), match.group(3)
    if period:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if period == "PM" else 0)
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def parse_day_list(value):
    days = set()
    for part in (value or "").split(","):
        if not part.strip():
            continue
        day = DAY_ALIASES.get(part.strip().casefold())
        if day is None:
            raise ValueError("Use comma-separated days such as M,T,Th,F.")
        days.add(day)
    return days


def parse_time_slot(value):
    if not (value or "").strip():
        return [], None

    meetings = []
    for entry in value.split(";"):
        if not entry.strip():
            continue
        match = _MEETING_RE.fullmatch(entry)
        if not match:
            return [], "unrecognized time format"

        start, end = to_minutes(match.group(2)), to_minutes(match.group(3))
        if start is None or end is None or end <= start:
            return [], "invalid start or end time"

        for part in match.group(1).split(","):
            day = DAY_ALIASES.get(part.strip().casefold())
            if day is None:
                return [], "unrecognized weekday"
            meetings.append((day, start, end))

    return meetings, None


def parse_meetings(value):
    return parse_time_slot(value)[0]

def meetings_conflict(first, second):
    for day_a, start_a, end_a in first:
        for day_b, start_b, end_b in second:
            if day_a == day_b and start_a < end_b and start_b < end_a:
                return True
    return False


def count_conflicts(meeting_lists):
    return sum(meetings_conflict(a, b) for a, b in combinations(meeting_lists, 2))


def gap_minutes(meetings):
    by_day = {}
    for day, start, end in meetings:
        by_day.setdefault(day, []).append((start, end))

    total = 0
    for day_meetings in by_day.values():
        day_meetings.sort()
        last_end = day_meetings[0][1]
        for start, end in day_meetings[1:]:
            total += max(0, start - last_end)
            last_end = max(last_end, end)
    return total

def read_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def find_data_dir():
    here = Path(__file__).resolve().parent
    if DATA_DIR:
        # a relative DATA_DIR such as "../filtered/" is tried from this file's folder first,
        # then from the folder the program was launched in
        for folder in (here / DATA_DIR, Path(DATA_DIR)):
            if (folder / CURRICULUM_FILENAME).exists():
                return folder
    candidates = [here.parent / "filtered", here / "filtered", Path("../filtered"),
                  Path("filtered"), Path(".")]
    for folder in candidates:
        if (folder / CURRICULUM_FILENAME).exists():
            return folder
    raise FileNotFoundError(f"curriculum file '{CURRICULUM_FILENAME}' not found.")


def load_term_data(program, specialization, year, semester):
    folder = find_data_dir()
    year_key = YEAR_MAP.get(year, str(year))
    sem_key = SEMESTER_MAP.get(semester, str(semester))

    required, specialized, elective, ge = [], [], [], []
    for row in read_csv(folder / CURRICULUM_FILENAME):
        if row["program"] != program or row["specialization"] != specialization:
            continue
        if row["course_type"] == "SPECIALIZED":
            specialized.append(row)
        elif row["course_type"] == "GE ELECTIVE":
            ge.append(row)
        elif row["is_elective"] == "Yes":
            elective.append(row)
        elif row["year"] == year_key and row["semester"] == sem_key:
            required.append(row)

    valid_codes = {r["course_code"] for r in required + specialized + elective + ge}
    sections = [row for row in read_csv(folder / SEMESTER_FILES.get(sem_key, SEMESTER_FILES["2"]))
                if row["course_code"] in valid_codes]
    for section in sections:
        section["meetings"] = parse_meetings(section["time_slot"])

    return required, specialized, elective, ge, sections



def chromosome_to_schedule(chromosome):
    return [section for section in chromosome.values() if section is not None]


def count_blocked(sections, blocked_times):
    meetings = [m for s in sections for m in s["meetings"]]
    count = 0
    for block in set(blocked_times):
        if meetings_conflict(meetings, [block]):
            count += 1
    return count


def evaluate_schedule(sections, course_units, required_codes, blocked_times=(),
                      max_units=MAX_UNITS, max_non_academic_units=None,
                      non_academic_prefixes=NON_ACADEMIC_PREFIXES):
    scheduled_codes = {s["course_code"] for s in sections}

    academic_units = 0
    non_academic_units = 0
    for code in scheduled_codes:
        units = course_units.get(code, 0)
        if is_non_academic_course(code, non_academic_prefixes):
            non_academic_units += units
        else:
            academic_units += units

    excess_units = max(0, academic_units - max_units)
    if max_non_academic_units is not None:
        excess_units += max(0, non_academic_units - max_non_academic_units)

    conflicts = count_conflicts([s["meetings"] for s in sections])
    missing_required = len(set(required_codes) - scheduled_codes)

    metrics = {
        "conflicts": conflicts,
        "academic_units": academic_units,
        "non_academic_units": non_academic_units,
        "excess_units": excess_units,
        "missing_required": missing_required,
        "gap_minutes": gap_minutes([m for s in sections for m in s["meetings"]]),
        "blocked_count": count_blocked(sections, blocked_times),
    }
    metrics["valid"] = (conflicts == 0 and excess_units == 0 and missing_required == 0)
    return metrics


def fitness_from_metrics(metrics):
    hard = metrics["conflicts"] + metrics["excess_units"] + metrics["missing_required"]
    return (metrics["academic_units"]
            - HARD_CONSTRAINT_WEIGHT * hard
            - SOFT_CONSTRAINT_WEIGHT * metrics["gap_minutes"]
            - metrics["blocked_count"])


def solve_fitness(sections, course_units, required_codes, blocked_times=(), **kwargs):
    return fitness_from_metrics(
        evaluate_schedule(sections, course_units, required_codes, blocked_times, **kwargs)
    )


def is_valid_schedule(sections, course_units, required_codes, **kwargs):
    return evaluate_schedule(sections, course_units, required_codes, **kwargs)["valid"]


def print_evaluation(sections, course_units, required_codes, blocked_times=(),
                     max_units=MAX_UNITS, **kwargs):
    metrics = evaluate_schedule(sections, course_units, required_codes, blocked_times,
                                max_units=max_units, **kwargs)

    print(f"{'Course':<14} {'Section':<10} {'Units':<7} Meeting times")
    print("-" * 65)
    for s in sorted(sections, key=lambda s: s["course_code"]):
        code = s["course_code"]
        label = str(course_units.get(code, 0))
        if is_non_academic_course(code, NON_ACADEMIC_PREFIXES):
            label += " (HK)"
        print(f"{code:<14} {s.get('section', '-'):<10} {label:<7} {s.get('time_slot', '')}")

    print(f"\nAcademic units : {metrics['academic_units']} / {max_units}")
    print(f"Conflicts      : {metrics['conflicts']}")
    print(f"Missing reqd   : {metrics['missing_required']}")
    print(f"Gap minutes    : {metrics['gap_minutes']}")
    print(f"Blocked hit    : {metrics['blocked_count']}")
    print(f"Valid          : {metrics['valid']}")
    print(f"Fitness        : {fitness_from_metrics(metrics):.2f}")
    return metrics
