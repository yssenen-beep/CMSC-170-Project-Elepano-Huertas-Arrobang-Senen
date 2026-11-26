import heapq
from itertools import count
from helper import (
    MAX_UNITS, SEARCH_NODE_LIMIT, SOFT_CONSTRAINT_WEIGHT,
    gap_minutes, load_term_data, meetings_conflict, parse_integer, to_minutes,
)
from helper import evaluate_schedule, fitness_from_metrics, is_non_academic_course

MAXIMUM_NODES = SEARCH_NODE_LIMIT
UNIT_WEIGHT = 1.0

def has_conflict(a, b):
    return meetings_conflict(a["meetings"], b["meetings"])


def gap_cost(sections, preferred_gap=0):
    all_meetings = [m for s in sections for m in s["meetings"]]
    if not preferred_gap:
        return gap_minutes(all_meetings)
    # compute the total gap cost for the given preferred gap
    by_day = {}
    for day, start, end in all_meetings:
        by_day.setdefault(day, []).append((start, end))
    cost = 0.0
    for intervals in by_day.values():
        intervals.sort()
        last_end = intervals[0][1]
        for start, end in intervals[1:]:
            cost += abs(max(0, start - last_end) - preferred_gap)
            last_end = max(last_end, end)
    return cost

def blocked_cost(sections):
    return len(set().union(*(s["blocked"] for s in sections)))

def setup_a_star_inputs(program, specialization, year, semester, blocked):
    #blocked is a list of (day, start_min, end_min) times the student prefers to keep vacant
    req, spec, elec, ge, schedules = load_term_data(program, specialization, year, semester)

    course_units = {}
    for c in req + spec + elec + ge:
        units = parse_integer(c["units"])
        if units is not None:
            course_units[c["course_code"]] = units

    options = {}
    for section in schedules:
        if not section["meetings"]:
            continue    #sections with no time allotted are ignored
        section["blocked"] = {b for b in blocked if meetings_conflict(section["meetings"], [b])}
        options.setdefault(section["course_code"], []).append(section)

    #required courses with no units and no time specified are still taken
    for c in req:
        if not c["units"].strip() and c["course_code"] not in options:
            options[c["course_code"]] = [{"course_code": c["course_code"], "section": "-", "time_slot": "No time allotted",
                                          "meetings": [], "blocked": set()}]

    req_codes = {c["course_code"] for c in req}
    opt_codes = []
    for c in spec + elec + ge:
        code = c["course_code"]
        if code not in req_codes and code not in opt_codes and options.get(code) and course_units.get(code, 0) > 0 and not is_non_academic_course(code):
            opt_codes.append(code)

    return options, course_units, req_codes, opt_codes

def print_a_star_results(schedule, course_units, fitness, academic_units, nodes):
    print(f"nodes expanded: {nodes}")
    print(f"best schedule: {academic_units} academic units out of {MAX_UNITS} max units")
    print(f"fitness value: {fitness:.2f}")
    print(f"{'course':<14} {'section':<10} {'units':<7} meeting times")
    print("-" * 65)

    for section in sorted(schedule, key=lambda s: s["course_code"]):
        code = section["course_code"]
        units_label = str(course_units.get(code, 0))
        if is_non_academic_course(code):
            units_label += " (hk)"
        print(f"{code:<14} {section['section']:<10} {units_label:<7} {section['time_slot']}")

def a_star(program, specialization, year, semester, blocked_times=(), preferred_gap=0):
    print("solving timetable...")
    preferred_gap = preferred_gap or 0
    blocked = [(day, to_minutes(start), to_minutes(end)) for day, start, end in blocked_times]
    options, course_units, req_codes, opt_codes = setup_a_star_inputs(program, specialization, year, semester, blocked)

    if not req_codes:
        print("no required courses found for this program/specialization.")
        return []

    missing = sorted(c for c in req_codes if not options.get(c))
    if missing:
        print(f"error: required courses have no sections: {', '.join(missing)}")
        return []

    req_units = sum(course_units.get(c, 0) for c in req_codes if not is_non_academic_course(c))
    if req_units > MAX_UNITS:
        print(f"error: required courses total {req_units} units, exceeding the {MAX_UNITS}-unit cap.")
        return []

    req_order = sorted(req_codes, key=lambda c: len(options[c]))
    opt_order = sorted(opt_codes, key=lambda c: len(options[c]))
    codes = req_order + opt_order
    n_req = len(req_order)

    full = (1 << (MAX_UNITS + 1)) - 1
    reach = [0] * (len(codes) + 1)
    reach[len(codes)] = 1
    for i in range(len(codes) - 1, -1, -1):
        u = 0 if is_non_academic_course(codes[i]) else course_units.get(codes[i], 0)
        taken = (reach[i + 1] << u) & full
        reach[i] = taken if i < n_req else (reach[i + 1] | taken)

    def shortfall(units, next_depth):
        totals = (reach[next_depth] << units) & full
        return None if totals == 0 else MAX_UNITS - (totals.bit_length() - 1)

    #classes added later can reduce gap_cost by at most sum(e - s + preferred_gap) per course (keeps h(n) admissible)
    rest_minutes = [0] * (len(codes) + 1)
    for i in range(len(codes) - 1, -1, -1):
        rest_minutes[i] = rest_minutes[i + 1] + max(
            (sum(e - s + preferred_gap for _, s, e in sec["meetings"]) for sec in options.get(codes[i], [])),
            default=0,
        )

    def soft_cost(chosen, depth):
        gap = gap_cost(chosen, preferred_gap)
        return SOFT_CONSTRAINT_WEIGHT * max(0, gap - rest_minutes[depth]) + blocked_cost(chosen), gap

    def show(chosen, units):
        metrics = evaluate_schedule(chosen, course_units, req_codes, blocked)
        if not metrics["valid"]:
            print("no valid schedule found in this run.")
            return []

        fitness = fitness_from_metrics(metrics)
        if preferred_gap:
            fitness += SOFT_CONSTRAINT_WEIGHT * (metrics["gap_minutes"] - gap_cost(chosen, preferred_gap))
        print_a_star_results(chosen, course_units, fitness, metrics["academic_units"], nodes)
        return list(chosen)

    tie = count()
    frontier = [(0.0, 0, 0, next(tie), 0, (), 0)]
    nodes = 0

    while frontier and nodes < MAXIMUM_NODES:
        f, _, _, _, depth, chosen, units = heapq.heappop(frontier)
        nodes += 1

        if depth == len(codes):
            return show(chosen, units)

        code = codes[depth]
        code_units = 0 if is_non_academic_course(code) else course_units.get(code, 0)

        #try assigning a section to the current course
        if units + code_units <= MAX_UNITS:
            for section in options[code]:
                if any(has_conflict(section, other) for other in chosen):
                    continue
                new_chosen = chosen + (section,)
                new_units = units + code_units
                short = shortfall(new_units, depth + 1)
                if short is None:
                    continue
                g, gap = soft_cost(new_chosen, depth + 1)
                h = UNIT_WEIGHT * short
                heapq.heappush(frontier, (g + h, gap, -(depth + 1), next(tie), depth + 1, new_chosen, new_units))

        #option 2: skip course (only allowed for optional/elective courses)
        if depth >= n_req:
            short = shortfall(units, depth + 1)
            if short is not None:
                g, gap = soft_cost(chosen, depth + 1)
                h = UNIT_WEIGHT * short
                heapq.heappush(frontier, (g + h, gap, -(depth + 1), next(tie), depth + 1, chosen, units))

    #node limit reached: show the best complete schedule still waiting in the frontier
    complete = [node for node in frontier if node[4] == len(codes)]
    if complete:
        print("node limit reached, showing the best schedule found so far (not guaranteed best).")
        _, _, _, _, _, chosen, units = min(complete)
        return show(chosen, units)

    print("no valid schedule found within search limits.")
    return []

if __name__ == "__main__":
    test_cases = [
        ("BSChE", "GENERAL_ENGINEERING_INDUSTRY_RESEARCH", "1st year", "1st Semester"),
        ("BSCE", "GENERAL", "3rd year", "2nd Semester"),
        ("BSEE", "COMPUTER_ENGG_GENERAL", "1st year", "1st Semester"),
    ]

    for case in test_cases:
        print("\n" + " | ".join(case))
        a_star(*case)