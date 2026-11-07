import csv
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FILTERED_DIR = ROOT / "filtered"
CURRICULUM_FILE = FILTERED_DIR / "ceat_program_courses.csv"
SEMESTER_FILES = {
    1: FILTERED_DIR / "ceat_class_schedule_1st_sem.csv",
    2: FILTERED_DIR / "ceat_class_schedule_2nd_sem.csv",
}
SEMESTER_NAMES = {1: "1st Semester", 2: "2nd Semester"}
SEARCH_NODE_LIMIT = 100_000

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
TIME_SLOT_RE = re.compile(
    r"^\s*(.*?)\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*$"
)
TIME_RANGE_RE = re.compile(r"^\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*$")


def normalize(value):
    # Normalize case and repeated whitespace for matching CSV values.
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


def parse_clock(value):
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", value or "")
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def parse_day_list(value):
    # Parse comma-separated day names into a set of normalized day tokens.
    if not value.strip():
        return set()
    days = set()
    for part in value.split(","):
        day = DAY_ALIASES.get(part.strip().casefold())
        if day is None:
            raise ValueError("Use comma-separated days such as M,T,Th,F.")
        days.add(day)
    return days


def parse_time_slot(value):
    # Return (meetings, error), where meetings are (day, start, end) tuples.
    if not (value or "").strip():
        return (), None

    match = TIME_SLOT_RE.fullmatch(value)
    if not match:
        return (), "unrecognized time format"

    start, end = parse_clock(match.group(2)), parse_clock(match.group(3))
    if start is None or end is None or end <= start:
        return (), "invalid start or end time"

    days = []
    for part in match.group(1).split(","):
        day = DAY_ALIASES.get(part.strip().casefold())
        if day is None:
            return (), "unrecognized weekday"
        days.append(day)

    if not days:
        return (), "no weekdays"
    meetings = tuple((day, start, end) for day in days)
    return meetings, None


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def choose_value(label, values):
    # Prompt for a value or its 1-based number in a displayed list.
    values = list(values)
    print("\n" + label + ":")
    for index, value in enumerate(values, start=1):
        print(f"  {index}. {value}")

    while True:
        answer = input("Choose a number or type a value: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(values):
            return values[int(answer) - 1]
        match = next((value for value in values if normalize(value) == normalize(answer)), None)
        if match is not None:
            return match
        print("That choice is not in the list. Try again.")


def get_curriculum_courses(rows, program, specialization, year, semester):
    # Return the selected term's distinct course records in plan order.
    courses = []
    seen = set()
    for row in rows:
        if normalize(row.get("program")) != normalize(program):
            continue
        if normalize(row.get("specialization")) != normalize(specialization):
            continue
        if parse_integer(row.get("year")) != year:
            continue
        if parse_integer(row.get("semester")) != semester:
            continue

        code = (row.get("course_code") or "").strip()
        key = normalize(code)
        if not key or key in seen:
            continue

        seen.add(key)
        courses.append({
            "course_code": code,
            "course_title": (row.get("course_title") or "").strip(),
            "units": parse_number(row.get("units")),
            "course_type": (row.get("course_type") or "").strip(),
        })
    return courses


def load_offerings(path):
    # Group one-row section offerings by normalized course code.
    by_course = {}
    invalid_times = []

    for row_number, row in enumerate(read_csv(path), start=2):
        code = (row.get("course_code") or "").strip()
        key = normalize(code)
        if not key:
            continue

        raw_slot = (row.get("time_slot") or "").strip()
        meetings, error = parse_time_slot(raw_slot)
        if error:
            invalid_times.append((row_number, code, raw_slot, error))
            continue

        option = {
            "course_code": code,
            "units": parse_number(row.get("units")),
            "class_type": (row.get("class_type") or "").strip(),
            "section": (row.get("section") or "").strip(),
            "time_slot": raw_slot,
            "meetings": meetings,
        }
        by_course.setdefault(key, []).append(option)

    return by_course, invalid_times


def ask_preferences():
    print("\nOptional preferences (these affect scoring, not eligibility).")
    print("Press Enter to skip a preference.")

    preferred_days = None
    while True:
        raw_days = input("Preferred class days, e.g. M,T,Th (blank for any): ").strip()
        if not raw_days:
            break
        try:
            preferred_days = parse_day_list(raw_days)
            break
        except ValueError as error:
            print(error)

    preferred_window = None
    while True:
        raw_window = input("Preferred time range, e.g. 08:00-13:00 (blank for any): ").strip()
        if not raw_window:
            break
        match = TIME_RANGE_RE.fullmatch(raw_window)
        if not match:
            print("Use a time range such as 08:00-13:00.")
            continue
        start, end = parse_clock(match.group(1)), parse_clock(match.group(2))
        if start is None or end is None or end <= start:
            print("Enter a valid range whose end is after its start.")
            continue
        preferred_window = (start, end)
        break

    preferred_gap = None
    while True:
        raw_gap = input("Preferred gap between classes in minutes (blank to skip): ").strip()
        if not raw_gap:
            break
        try:
            preferred_gap = int(raw_gap)
            if preferred_gap < 0:
                raise ValueError
            break
        except ValueError:
            print("Enter a non-negative whole number of minutes.")

    return {
        "days": preferred_days,
        "window": preferred_window,
        "gap": preferred_gap,
    }


def meetings_conflict(first, second):
    for day_a, start_a, end_a in first:
        for day_b, start_b, end_b in second:
            if day_a == day_b and start_a < end_b and start_b < end_a:
                return True
    return False


def option_fits(option, selected):
    for _, chosen in selected:
        if meetings_conflict(option["meetings"], chosen["meetings"]):
            return False
    return True


def score_schedule(selected, preferences):
    # Score availability and gap fit as the mean of measurable preferences.
    all_meetings = []
    for _, option in selected:
        all_meetings.extend(option["meetings"])

    components = {}

    if preferences["days"] is not None or preferences["window"] is not None:
        total_minutes = 0
        preferred_minutes = 0
        for day, start, end in all_meetings:
            duration = end - start
            total_minutes += duration

            if preferences["days"] is not None and day not in preferences["days"]:
                continue

            if preferences["window"] is None:
                preferred_minutes += duration
            else:
                window_start, window_end = preferences["window"]
                preferred_minutes += max(0, min(end, window_end) - max(start, window_start))

        if total_minutes:
            components["availability"] = 100.0 * preferred_minutes / total_minutes

    if preferences["gap"] is not None:
        by_day = {}
        for day, start, end in all_meetings:
            by_day.setdefault(day, []).append((start, end))

        gaps = []
        for day_meetings in by_day.values():
            day_meetings.sort()
            for index in range(1, len(day_meetings)):
                previous_end = day_meetings[index - 1][1]
                next_start = day_meetings[index][0]
                if next_start >= previous_end:
                    gaps.append(next_start - previous_end)

        if gaps:
            target = preferences["gap"]
            tolerance = max(60, target)
            gap_score = sum(
                max(0.0, 100.0 * (1.0 - abs(gap - target) / tolerance))
                for gap in gaps
            ) / len(gaps)
            components["gap"] = gap_score

    overall = sum(components.values()) / len(components) if components else None
    return {"components": components, "overall": overall}


def search_schedule(courses, offerings, preferences):
    # Use recursive backtracking to find the best schedule within a node budget.
    ordered_courses = sorted(
        courses,
        key=lambda course: len(offerings[normalize(course["course_code"])]),
    )

    best_schedule = None
    best_score = -1.0
    expanded_nodes = 0
    limit_reached = False
    stop_search = False
    any_preference = (
        preferences["days"] is not None
        or preferences["window"] is not None
        or preferences["gap"] is not None
    )

    def backtrack(index, selected):
        nonlocal best_schedule, best_score, expanded_nodes, limit_reached, stop_search

        if stop_search:
            return
        if expanded_nodes >= SEARCH_NODE_LIMIT:
            limit_reached = True
            return
        expanded_nodes += 1

        if index == len(ordered_courses):
            result = score_schedule(selected, preferences)
            score = result["overall"]
            comparable_score = score if score is not None else 0.0
            if comparable_score > best_score:
                best_score = comparable_score
                best_schedule = list(selected)

            if not any_preference or comparable_score >= 100.0:
                stop_search = True
            return

        course = ordered_courses[index]
        course_options = offerings[normalize(course["course_code"])]
        candidates = []

        for option in course_options:
            if not option_fits(option, selected):
                continue
            trial = selected + [(course, option)]
            partial_score = score_schedule(trial, preferences)["overall"]
            candidates.append((partial_score if partial_score is not None else -1.0, option))

        candidates.sort(key=lambda item: item[0], reverse=True)

        for _, option in candidates:
            if stop_search:
                return
            selected.append((course, option))
            backtrack(index + 1, selected)
            selected.pop()
            if limit_reached:
                return

    backtrack(0, [])
    return best_schedule, best_score, expanded_nodes, limit_reached


def format_units(value):
    if value is None:
        return "?"
    if value.is_integer():
        return str(int(value))
    return f"{value:g}"


def format_score(value):
    return "not measurable" if value is None else f"{value:.1f}/100"


def print_schedule(program, specialization, year, semester, courses, selected, score, preferences):
    chosen_by_course = {
        normalize(course["course_code"]): option for course, option in selected
    }

    print("\nViable schedule")
    print(f"Program: {program}")
    print(f"Development program / specialization: {specialization}")
    print(f"Year: {year}")
    print(f"Semester: {SEMESTER_NAMES[semester]}")
    print(f"Preference score: {format_score(score)}")

    if preferences["days"] is not None or preferences["window"] is not None:
        availability = score_schedule(selected, preferences)["components"].get("availability")
        print(f"  Availability fit: {format_score(availability)}")
    if preferences["gap"] is not None:
        gap = score_schedule(selected, preferences)["components"].get("gap")
        print(f"  Gap fit (target {preferences['gap']} min): {format_score(gap)}")

    headers = ("Course", "Section", "Type", "Units", "Meeting times")
    table = []
    total_units = 0.0
    for course in courses:
        option = chosen_by_course[normalize(course["course_code"])]
        units = option["units"]
        if units is None:
            units = course["units"]
        if units is not None:
            total_units += units
        table.append((
            course["course_code"],
            option["section"] or "(unlabeled)",
            option["class_type"] or "—",
            format_units(units),
            option["time_slot"] or "TBA / no fixed time",
        ))

    widths = [
        max(len(headers[index]), *(len(row[index]) for row in table))
        for index in range(len(headers))
    ]
    print()
    print("  ".join(headers[index].ljust(widths[index]) for index in range(len(headers))))
    print("  ".join("-" * width for width in widths))
    for row in table:
        print("  ".join(row[index].ljust(widths[index]) for index in range(len(headers))))
    print(f"\nCourses scheduled: {len(table)} / {len(courses)}")
    print(f"Total units: {format_units(total_units)}")


def main():
    try:
        curriculum_rows = read_csv(CURRICULUM_FILE)
    except FileNotFoundError:
        print(f"Could not find the curriculum file: {CURRICULUM_FILE}")
        return 1

    programs = sorted(
        {row["program"].strip() for row in curriculum_rows if row.get("program", "").strip()},
        key=str.casefold,
    )
    if not programs:
        print("No programs were found in the filtered curriculum file.")
        return 1

    program = choose_value("Available CEAT programs", programs)
    specializations = sorted(
        {
            row["specialization"].strip()
            for row in curriculum_rows
            if normalize(row.get("program")) == normalize(program)
            and row.get("specialization", "").strip()
        },
        key=str.casefold,
    )
    if not specializations:
        print(f"No development programs / specializations were found for {program}.")
        return 1

    specialization = choose_value(
        f"Development programs / specializations for {program}",
        specializations,
    )
    matching_rows = [
        row for row in curriculum_rows
        if normalize(row.get("program")) == normalize(program)
        and normalize(row.get("specialization")) == normalize(specialization)
    ]
    year_values = set()
    for row in matching_rows:
        parsed_year = parse_integer(row.get("year"))
        if parsed_year is not None:
            year_values.add(parsed_year)
    years = sorted(year_values)
    if not years:
        print("No year values were found for that program and specialization.")
        return 1

    year = int(choose_value("Available years", [str(value) for value in years]))
    semester_values = set()
    for row in matching_rows:
        parsed_semester = parse_integer(row.get("semester"))
        if (
            parse_integer(row.get("year")) == year
            and parsed_semester in SEMESTER_FILES
        ):
            semester_values.add(parsed_semester)
    semester_values = sorted(semester_values)
    if not semester_values:
        print(
            "There are no first- or second-semester plan courses for that year. "
            "The filtered schedule files currently cover semesters 1 and 2 only."
        )
        return 1

    semester = int(choose_value(
        "Available semesters",
        [f"{value} - {SEMESTER_NAMES[value]}" for value in semester_values],
    ).split(" - ", 1)[0])

    courses = get_curriculum_courses(
        matching_rows, program, specialization, year, semester
    )
    if not courses:
        print("No courses were found for that program, year, and semester.")
        return 1

    schedule_path = SEMESTER_FILES[semester]
    try:
        offerings, invalid_times = load_offerings(schedule_path)
    except FileNotFoundError:
        print(f"Could not find the class schedule file: {schedule_path}")
        return 1

    if invalid_times:
        print(
            f"\nWarning: skipped {len(invalid_times)} class rows with unrecognized "
            "non-empty time slots."
        )
        for row_number, code, slot, error in invalid_times[:5]:
            print(f"  CSV row {row_number}, {code}, {slot!r}: {error}")

    unavailable = [
        course["course_code"]
        for course in courses
        if not offerings.get(normalize(course["course_code"]))
    ]
    if unavailable:
        print("\nNo section offerings were found for these plan courses:")
        for code in unavailable:
            print(f"  - {code}")
        print("A complete schedule cannot be built from the current filtered data.")
        return 1

    print(
        f"\nPlanning {len(courses)} course(s) for {program} / {specialization}, "
        f"Year {year}, {SEMESTER_NAMES[semester]}."
    )
    preferences = ask_preferences()
    best, best_score, expanded_nodes, limit_reached = search_schedule(
        courses, offerings, preferences
    )

    if best is None:
        if limit_reached:
            print(
                f"\nNo viable schedule was found within the {SEARCH_NODE_LIMIT:,}-node "
                "search limit."
            )
        else:
            print("\nNo conflict-free schedule exists in the current filtered offerings.")
        return 1

    if limit_reached:
        print(
            f"\nSearch reached its {SEARCH_NODE_LIMIT:,}-node limit after "
            f"{expanded_nodes:,} nodes; showing the best schedule found so far."
        )
    elif any(
        preferences[key] is not None
        for key in ("days", "window", "gap")
    ):
        print(f"\nSearch examined {expanded_nodes:,} nodes.")

    final_score = score_schedule(best, preferences)["overall"]
    print_schedule(
        program, specialization, year, semester,
        courses, best, final_score, preferences,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())


