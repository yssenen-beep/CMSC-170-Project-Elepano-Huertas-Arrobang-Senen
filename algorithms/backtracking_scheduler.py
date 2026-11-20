import re
import sys
from pathlib import Path
from helper import (
    DAY_ORDER, MAX_UNITS, MAX_NON_ACADEMIC_UNITS, SEARCH_NODE_LIMIT,
    is_non_academic_course as is_non_academic_code,
    meetings_conflict, normalize, parse_day_list, parse_integer, parse_number,
    parse_time_slot, read_csv, to_minutes,
)
from helper import evaluate_schedule, fitness_from_metrics


ROOT = Path(__file__).resolve().parent.parent
FILTERED_DIR = ROOT / "filtered"
CURRICULUM_FILE = FILTERED_DIR / "ceat_program_courses.csv"
SEMESTER_FILES = {
    1: FILTERED_DIR / "ceat_class_schedule_1st_sem.csv",
    2: FILTERED_DIR / "ceat_class_schedule_2nd_sem.csv",
}
SEMESTER_NAMES = {1: "1st Semester", 2: "2nd Semester"}
MAX_ACADEMIC_UNITS = MAX_UNITS

BLOCKED_PERIOD_RE = re.compile(
    r"^\s*(?:(.*?)\s+)?(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*$"
)
parse_clock = to_minutes

def parse_blocked_periods(value):
    # Parse periods such as 'M,T 08:00-10:00; W 13:00-15:00'.
    periods = []
    for raw_period in value.split(";"):
        match = BLOCKED_PERIOD_RE.fullmatch(raw_period)
        if not match:
            raise ValueError(
                "Use 'M,T 08:00-10:00' for selected days, or "
                "'08:00-10:00' to block that time every day."
            )

        raw_days = (match.group(1) or "").strip()
        days = parse_day_list(raw_days) if raw_days else None
        start, end = parse_clock(match.group(2)), parse_clock(match.group(3))
        if start is None or end is None or end <= start:
            raise ValueError("Each blocked time range must be valid and end after it starts.")
        periods.append({"days": days, "window": (start, end)})

    return periods

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
    print("\nSet optional soft preferences for blocked times and class gaps.")
    print("The search may use a blocked time if that leads to a valid schedule.")

    blocked_periods = []
    while True:
        raw_periods = input(
            "Blocked times, e.g. M,T 08:00-10:00; W,F 13:00-15:00 "
            "(blank to skip): "
        ).strip()
        if not raw_periods:
            break
        try:
            blocked_periods = parse_blocked_periods(raw_periods)
            break
        except ValueError as error:
            print(error)

    preferred_gap = None
    while True:
        raw_gap = input("Target gap between classes in minutes (blank to skip): ").strip()
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
        "blocked_periods": blocked_periods,
        "gap": preferred_gap,
    }

def option_fits(option, selected):
    for _, chosen in selected:
        if meetings_conflict(option["meetings"], chosen["meetings"]):
            return False
    return True


def blocked_minutes_for_meeting(day, start, end, blocked_periods):
    # Merge matching block overlaps so overlapping blocks are not double-counted.
    overlaps = []
    for period in blocked_periods:
        if period["days"] is not None and day not in period["days"]:
            continue
        block_start, block_end = period["window"]
        overlap_start = max(start, block_start)
        overlap_end = min(end, block_end)
        if overlap_start < overlap_end:
            overlaps.append((overlap_start, overlap_end))

    overlaps.sort()
    if not overlaps:
        return 0

    total = 0
    merged_start, merged_end = overlaps[0]
    for overlap_start, overlap_end in overlaps[1:]:
        if overlap_start <= merged_end:
            merged_end = max(merged_end, overlap_end)
        else:
            total += merged_end - merged_start
            merged_start, merged_end = overlap_start, overlap_end
    return total + merged_end - merged_start

def is_non_academic_course(course):
    # HK and NSTP units have a separate limit from academic course units.
    return is_non_academic_code(course.get("course_code"))


def get_course_units(course, option):
    # Prefer the section's units, falling back to the curriculum when absent.
    if option["units"] is not None:
        return option["units"]
    return course["units"]


def unit_totals(selected):
    academic = 0.0
    non_academic = 0.0
    for course, option in selected:
        units = get_course_units(course, option)
        if units is None:
            continue
        if is_non_academic_course(course):
            non_academic += units
        else:
            academic += units
    return academic, non_academic


def option_within_unit_limits(
    course, option, selected,
    max_academic_units=MAX_ACADEMIC_UNITS,
    max_non_academic_units=MAX_NON_ACADEMIC_UNITS,
):
    academic, non_academic = unit_totals(selected)
    units = get_course_units(course, option)
    if units is not None:
        if is_non_academic_course(course):
            non_academic += units
        else:
            academic += units
    return (
        academic <= max_academic_units
        and non_academic <= max_non_academic_units
    )


def score_schedule(selected, preferences):
    # Score soft preferences; hard constraints are checked during search.
    all_meetings = []
    for _, option in selected:
        all_meetings.extend(option["meetings"])

    components = {}

    if preferences["blocked_periods"]:
        total_minutes = sum(end - start for _, start, end in all_meetings)
        blocked_minutes = sum(
            blocked_minutes_for_meeting(day, start, end, preferences["blocked_periods"])
            for day, start, end in all_meetings
        )
        if total_minutes:
            components["blocked_time"] = (
                100.0 * (total_minutes - blocked_minutes) / total_minutes
            )

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


def search_schedule(
    courses, offerings, preferences,
    max_academic_units=MAX_ACADEMIC_UNITS,
    max_non_academic_units=MAX_NON_ACADEMIC_UNITS,
):
    # Use recursive backtracking to find the best schedule within a node budget.
    if max_academic_units is None:
        max_academic_units = MAX_ACADEMIC_UNITS
    if max_non_academic_units is None:
        max_non_academic_units = MAX_NON_ACADEMIC_UNITS

    ordered_courses = sorted(
        courses,
        key=lambda course: len(offerings[normalize(course["course_code"])]),
    )

    best_schedule = None
    best_score = -1.0
    expanded_nodes = 0
    limit_reached = False
    stop_search = False
    any_preference = bool(preferences["blocked_periods"]) or preferences["gap"] is not None

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

            if not any_preference or score is None or comparable_score >= 100.0:
                stop_search = True
            return

        course = ordered_courses[index]
        course_options = offerings[normalize(course["course_code"])]
        candidates = []

        for option in course_options:
            if (
                not option_fits(option, selected)
                or not option_within_unit_limits(
                    course, option, selected,
                    max_academic_units, max_non_academic_units,
                )
            ):
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

    if preferences["blocked_periods"]:
        blocked_time = score_schedule(selected, preferences)["components"].get("blocked_time")
        print(f"  Blocked-time fit (time outside blocks): {format_score(blocked_time)}")
    if preferences["gap"] is not None:
        print(f"  Gap preference (target {preferences['gap']} min): {format_score(score)}")

    headers = ("Course", "Section", "Type", "Units", "Meeting times")
    table = []
    academic_units = 0.0
    non_academic_units = 0.0
    unknown_unit_courses = 0
    for course in courses:
        option = chosen_by_course[normalize(course["course_code"])]
        units = get_course_units(course, option)
        if units is None:
            unknown_unit_courses += 1
        else:
            if is_non_academic_course(course):
                non_academic_units += units
            else:
                academic_units += units
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
    print(f"Academic units: {format_units(academic_units)} / {MAX_ACADEMIC_UNITS}")
    print(
        "Non-academic units (HK/NSTP): "
        f"{format_units(non_academic_units)} / {MAX_NON_ACADEMIC_UNITS}"
    )
    if unknown_unit_courses:
        print(f"Units missing from data for {unknown_unit_courses} course(s).")


def blocked_periods_to_times(blocked_periods):
    # Turn blocked periods (days=None means every day) into (day, start_min, end_min) tuples
    # that the shared evaluation understands.
    times = []
    for period in blocked_periods:
        days = DAY_ORDER if period["days"] is None else period["days"]
        for day in days:
            times.append((day, *period["window"]))
    return times


def evaluate_selected(courses, selected, preferences):
    # Run the shared evaluation (same metrics and fitness as the GA and A*) on a finished schedule.
    sections = [option for _, option in selected]
    course_units = {
        course["course_code"]: get_course_units(course, option) or 0
        for course, option in selected
    }
    return evaluate_schedule(
        sections, course_units, {course["course_code"] for course in courses},
        blocked_periods_to_times(preferences["blocked_periods"]),
        max_units=MAX_ACADEMIC_UNITS, max_non_academic_units=MAX_NON_ACADEMIC_UNITS,
        non_academic_prefixes=("HK", "NSTP"),
    )


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
            print(
                "\nNo schedule satisfies the time-conflict and unit constraints "
                f"({MAX_ACADEMIC_UNITS} academic, "
                f"{MAX_NON_ACADEMIC_UNITS} non-academic units) in the current offerings."
            )
        return 1

    if limit_reached:
        print(
            f"\nSearch reached its {SEARCH_NODE_LIMIT:,}-node limit after "
            f"{expanded_nodes:,} nodes; showing the best schedule found so far."
        )
    elif preferences["gap"] is not None or preferences["blocked_periods"]:
        print(f"\nSearch examined {expanded_nodes:,} nodes.")

    final_score = score_schedule(best, preferences)["overall"]
    print_schedule(
        program, specialization, year, semester,
        courses, best, final_score, preferences,
    )
    metrics = evaluate_selected(courses, best, preferences)
    print(
        f"Shared fitness: {fitness_from_metrics(metrics):.2f} "
        f"(valid: {metrics['valid']}, gap minutes: {metrics['gap_minutes']}, "
        f"blocked times hit: {metrics['blocked_count']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
