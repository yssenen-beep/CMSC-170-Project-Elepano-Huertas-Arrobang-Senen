from helper import (
    MAX_UNITS, MAX_NON_ACADEMIC_UNITS, SEARCH_NODE_LIMIT,
    is_non_academic_course as is_non_academic_code, load_term_data,
    meetings_conflict, normalize, parse_number, to_minutes,
)

MAX_ACADEMIC_UNITS = MAX_UNITS


def course_record(row, required):
    return {
        "course_code": (row["course_code"] or "").strip(),
        "units": parse_number(row["units"]),
        "required": required,
    }


def load_courses_and_offerings(program, specialization, year, semester):
    # Read the term through helper.load_term_data (the same loader A* and the GA use),
    # then reshape it for the search: the term's plan courses without duplicates, the
    # optional courses that may fill up the units, and their sections grouped by normalized course code.
    required, specialized, electives, ge, sections = load_term_data(
        program, specialization, year, semester
    )

    courses = []
    seen = set()
    for row in required:
        key = normalize(row["course_code"])
        if not key or key in seen:
            continue
        seen.add(key)
        courses.append(course_record(row, required=True))

    offerings = {}
    invalid_times = []
    for section in sections:
        if section["time_slot"].strip() and not section["meetings"]:
            # helper.parse_meetings gives no meetings for a time slot it cannot read
            invalid_times.append((section["course_code"], section["time_slot"]))
            continue
        section["units"] = parse_number(section["units"])
        offerings.setdefault(normalize(section["course_code"]), []).append(section)

    # same rule as A* and the GA: a plan course with no units and no sections is still
    # taken, as a placeholder with no meeting time
    for course in courses:
        key = normalize(course["course_code"])
        if course["units"] is None and key not in offerings:
            offerings[key] = [{
                "course_code": course["course_code"],
                "units": 0.0,
                "class_type": "",
                "section": "-",
                "time_slot": "No time allotted",
                "meetings": [],
            }]

    # same pool as A* and the GA: specialized, elective and GE courses are optional
    # the search may add up to the unit cap, if they still have units
    for row in specialized + electives + ge:
        key = normalize(row["course_code"])
        timed = [option for option in offerings.get(key, []) if option["meetings"]]
        if key in seen or not parse_number(row["units"]) or not timed:
            continue
        if is_non_academic_code(row["course_code"]):
            continue
        seen.add(key)
        offerings[key] = timed
        courses.append(course_record(row, required=False))

    return courses, offerings, invalid_times


def option_fits(option, selected):
    return not any(meetings_conflict(option["meetings"], chosen["meetings"]) for _, chosen in selected)


def blocked_minutes_for_meeting(day, start, end, blocked_periods):
    # The UI sends blocked times as separate, non-overlapping runs per day,
    # so the overlaps can simply be added up.
    total = 0
    for period in blocked_periods:
        if day in period["days"]:
            block_start, block_end = period["window"]
            total += max(0, min(end, block_end) - max(start, block_start))
    return total

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
    academic, non_academic = unit_totals(selected + [(course, option)])
    return academic <= max_academic_units and non_academic <= max_non_academic_units


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
    # required courses must be placed, optional ones may be added or skipped, more academic units is better
    def option_count(course):
        return len(offerings[normalize(course["course_code"])])

    # required courses first, then optional ones, each with the fewest sections first (as A*)
    ordered_courses = (
        sorted((c for c in courses if c.get("required", True)), key=option_count)
        + sorted((c for c in courses if not c.get("required", True)), key=option_count)
    )

    # reachable[i]: academic unit totals the courses from position i on can still add
    # without passing the cap (required courses must be taken), like A*'s reach table
    reachable = [set() for _ in ordered_courses] + [{0.0}]
    for i in range(len(ordered_courses) - 1, -1, -1):
        course = ordered_courses[i]
        unit_choices = {0.0} if is_non_academic_course(course) else {
            get_course_units(course, option) or 0.0
            for option in offerings[normalize(course["course_code"])]
        }
        taken = {
            total + units
            for total in reachable[i + 1] for units in unit_choices
            if total + units <= max_academic_units
        }
        reachable[i] = taken if course.get("required", True) else taken | reachable[i + 1]
    if not reachable[0]:
        return None, -1.0, 0, False     # the required courses alone go over the unit cap
    unit_goal = max(reachable[0])

    best_schedule = None
    best_units = -1.0
    best_score = -1.0
    expanded_nodes = 0
    limit_reached = False
    stop_search = False
    any_preference = bool(preferences["blocked_periods"]) or preferences["gap"] is not None

    def backtrack(index, selected):
        nonlocal best_schedule, best_units, best_score, expanded_nodes, limit_reached, stop_search

        if stop_search:
            return
        if expanded_nodes >= SEARCH_NODE_LIMIT:
            limit_reached = True
            return

        academic, _ = unit_totals(selected)
        if best_schedule is not None:
            most_units = max(
                (academic + total for total in reachable[index]
                 if academic + total <= max_academic_units),
                default=None,
            )
            score_settled = not any_preference or best_score >= 100.0
            if most_units is None or most_units < best_units or (
                most_units == best_units and score_settled
            ):
                return      # this branch cannot beat the best schedule found so far
        expanded_nodes += 1

        if index == len(ordered_courses):
            result = score_schedule(selected, preferences)
            score = result["overall"]
            comparable_score = score if score is not None else 0.0
            if (academic, comparable_score) > (best_units, best_score):
                best_units, best_score = academic, comparable_score
                best_schedule = list(selected)

            if academic >= unit_goal and (
                not any_preference or score is None or comparable_score >= 100.0
            ):
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

        if not course.get("required", True) and not stop_search:
            backtrack(index + 1, selected)

    backtrack(0, [])
    return best_schedule, best_score, expanded_nodes, limit_reached


def print_results(selected, preferences, expanded_nodes, limit_reached):
    if limit_reached:
        print(f"node limit reached after {expanded_nodes:,} nodes, showing the best schedule found so far.")
    else:
        print(f"nodes expanded: {expanded_nodes:,}")

    academic, non_academic = unit_totals(selected)
    print(f"academic units: {academic:g} / {MAX_ACADEMIC_UNITS}, "
          f"non-academic units: {non_academic:g} / {MAX_NON_ACADEMIC_UNITS}")
    score = score_schedule(selected, preferences)["overall"]
    print("preference score: " + ("n/a" if score is None else f"{score:.1f} / 100"))
    print(f"{'course':<14} {'section':<10} {'units':<7} meeting times")
    print("-" * 65)

    for course, option in sorted(selected, key=lambda pair: pair[0]["course_code"]):
        units = get_course_units(course, option)
        label = "?" if units is None else f"{units:g}"
        if is_non_academic_course(course):
            label += " (hk)"
        print(f"{course['course_code']:<14} {option['section'] or '-':<10} {label:<7} "
              f"{option['time_slot'] or 'no time allotted'}")


def backtracking(program, specialization, year, semester, preferences):
    print("solving timetable...")
    courses, offerings, _invalid = load_courses_and_offerings(program, specialization, year, semester)
    if not courses:
        print("no courses found for this program/specialization.")
        return []

    missing = [c["course_code"] for c in courses if not offerings.get(normalize(c["course_code"]))]
    if missing:
        print(f"error: courses have no sections: {', '.join(missing)}")
        return []

    best, _score, nodes, limit_reached = search_schedule(courses, offerings, preferences)
    if best is None:
        print("no valid schedule found within search limits.")
        return []

    print_results(best, preferences, nodes, limit_reached)
    return best


if __name__ == "__main__":
    no_preferences = {"blocked_periods": [], "gap": None}
    # keep Monday 12:00-13:00 free and aim for 30-minute gaps between classes
    lunch_break = {
        "blocked_periods": [{"days": {"M"}, "window": (to_minutes("12:00"), to_minutes("13:00"))}],
        "gap": 30,
    }

    test_cases = [
        ("BSChE", "GENERAL_ENGINEERING_INDUSTRY_RESEARCH", "1st year", "1st Semester", no_preferences),
        ("BSCE", "GENERAL", "3rd year", "2nd Semester", lunch_break),
        ("BSEE", "COMPUTER_ENGG_GENERAL", "1st year", "1st Semester", no_preferences),
    ]

    for program, specialization, year, semester, preferences in test_cases:
        print("\n" + " | ".join((program, specialization, year, semester)))
        backtracking(program, specialization, year, semester, preferences)
