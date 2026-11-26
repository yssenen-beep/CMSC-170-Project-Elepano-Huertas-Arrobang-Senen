from helper import (
    MAX_UNITS, MAX_NON_ACADEMIC_UNITS, SEARCH_NODE_LIMIT,
    is_non_academic_course as is_non_academic_code, load_term_data,
    meetings_conflict, normalize, parse_number, to_minutes,
)

MAX_ACADEMIC_UNITS = MAX_UNITS


def load_courses_and_offerings(program, specialization, year, semester):
    # Read the term through helper.load_term_data (the same loader A* and the GA use),
    # then reshape it for the search: the term's plan courses without duplicates, and
    # their sections grouped by normalized course code.
    required, _specialized, _electives, _ge, sections = load_term_data(
        program, specialization, year, semester
    )

    courses = []
    seen = set()
    for row in required:
        code = (row["course_code"] or "").strip()
        key = normalize(code)
        if not key or key in seen:
            continue
        seen.add(key)
        courses.append({
            "course_code": code,
            "course_title": (row["course_title"] or "").strip(),
            "units": parse_number(row["units"]),
            "course_type": (row["course_type"] or "").strip(),
        })

    offerings = {}
    invalid_times = []
    for section in sections:
        code = (section["course_code"] or "").strip()
        raw_slot = (section["time_slot"] or "").strip()
        if raw_slot and not section["meetings"]:
            # helper.parse_meetings gives no meetings for a time slot it cannot read
            invalid_times.append((code, raw_slot))
            continue
        offerings.setdefault(normalize(code), []).append({
            "course_code": code,
            "units": parse_number(section["units"]),
            "class_type": (section["class_type"] or "").strip(),
            "section": (section["section"] or "").strip(),
            "time_slot": raw_slot,
            "meetings": section["meetings"],
        })

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

    return courses, offerings, invalid_times


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
