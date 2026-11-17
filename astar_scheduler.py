import csv
import os
import heapq
from itertools import combinations, count

BASE = "../filtered/"
MAX_UNITS = 21
MAXIMUM_NODES = 100000
UNIT_WEIGHT = 1.0   #penalty scale per unit under max limit
HARD_CONSTRAINT_WEIGHT = 1000   
SOFT_CONSTRAINT_WEIGHT = 0.01   #penalty per vacant minute

def parse_timeslot(time_slot):
    #parse meeting time strings into a list of (day, start, end) tuples
    if not time_slot or not time_slot.strip(): 
        return []

    meetings = []
    for entry in time_slot.split(";"):
        parts = entry.strip().split()
        if len(parts) < 2:
            continue
        days, time_range = parts[0], parts[1]
        start, end = time_range.split("-")
        for day in days.split(","):
            meetings.append((day, start, end))
    return meetings

def handle_file(program, specialization, year, semester):
    year_dict = {"1st year": "1", "2nd year": "2", "3rd year": "3", "4th year": "4"}
    semester_dict = {"1st Semester": "1", "2nd Semester": "2"}

    folder = next(
        (d for d in (BASE, ".", "filtered", "../filtered")
         if os.path.exists(os.path.join(d, "ceat_program_courses.csv"))),
        None
    )
    if folder is None:
        raise FileNotFoundError("curriculum file 'ceat_program_courses.csv' not found.")

    with open(os.path.join(folder, "ceat_program_courses.csv"), "r", encoding="utf-8") as f:
        courses = list(csv.DictReader(f))

    req, spec, elec, ge = [], [], [], []
    for row in courses:
        if row["program"] != program or row["specialization"] != specialization:
            continue
        if row["course_type"] == "SPECIALIZED":
            spec.append(row)
        elif row["course_type"] == "GE ELECTIVE":
            ge.append(row)
        elif row["is_elective"] == "Yes":
            elec.append(row)
        elif row["year"] == year_dict.get(year, year) and row["semester"] == semester_dict.get(semester, semester):
            req.append(row)

    sched_fname = "ceat_class_schedule_1st_sem.csv" if semester_dict.get(semester, semester) == "1" else "ceat_class_schedule_2nd_sem.csv"
    valid_codes = {r["course_code"] for r in req + spec + elec + ge}

    with open(os.path.join(folder, sched_fname), "r", encoding="utf-8") as sf:
        schedules = [row for row in csv.DictReader(sf) if row["course_code"] in valid_codes]

    for section in schedules:
        section["meetings"] = parse_timeslot(section["time_slot"])

    return req, spec, elec, ge, schedules

def to_minutes(time_str):
    #convert hh:mm or 12-hour format string to minutes elapsed from midnight
    time_str = time_str.strip()
    upper = time_str.upper()
    if "AM" in upper or "PM" in upper:
        clock, period = upper.split()
        h, m = map(int, clock.split(":"))
        if period == "PM" and h < 12:
            h += 12
        if period == "AM" and h == 12:
            h = 0
        return h * 60 + m
    h, m = map(int, time_str.split(":"))
    return h * 60 + m

def has_conflict(a, b):
    #check for time overlap between two class sections
    for dayA, startA, endA in a["mins"]:
        for dayB, startB, endB in b["mins"]:
            if dayA == dayB and startA < endB and startB < endA:
                return True
    return False

def gap_cost(sections):
    #calculate the total vacant minutes between classes in a day
    by_day = {}
    for s in sections:
        for day, start, end in s["mins"]:
            by_day.setdefault(day, []).append((start, end))

    cost = 0.0
    for meetings in by_day.values():
        meetings.sort()
        last_end = meetings[0][1]
        for start, end in meetings[1:]:
            cost += max(0, start - last_end)
            last_end = max(last_end, end)
    return cost

def blocked_cost(sections):
    #count each blocked time at most once if any class overlaps it
    return len(set().union(*(s["blocked"] for s in sections)))

def schedule_metrics(chosen, course_units, req_codes):
    #counts conflicts, units, and missing required courses
    conflicts = 0
    for a, b in combinations(chosen, 2):
        conflicts += has_conflict(a, b)

    academic_units = sum(course_units.get(s["course_code"], 0) for s in chosen if not s["course_code"].startswith("HK "))
    missing_required = len(req_codes - {s["course_code"] for s in chosen})
    return conflicts, academic_units, missing_required

def solve_fitness(chosen, course_units, req_codes):
    #fitness function: higher is better, penalizes conflicts, excess units, missing required courses, vacant minutes, and blocked times
    conflicts, academic_units, missing_required = schedule_metrics(chosen, course_units, req_codes)
    excess_units = max(0, academic_units - MAX_UNITS)
    return academic_units - HARD_CONSTRAINT_WEIGHT * (conflicts + excess_units + missing_required) - SOFT_CONSTRAINT_WEIGHT * gap_cost(chosen) - blocked_cost(chosen)

def setup_a_star_inputs(program, specialization, year, semester, blocked_times):
    req, spec, elec, ge, schedules = handle_file(program, specialization, year, semester)
    blocked = {(day, to_minutes(start), to_minutes(end)) for day, start, end in blocked_times}

    course_units = {}
    for c in req + spec + elec + ge:
        try:
            course_units[c["course_code"]] = int(float(c["units"]))
        except (ValueError, TypeError):
            pass

    options = {}
    for section in schedules:
        if not section["meetings"]:
            continue    #sections with no time allotted are ignored
        section["mins"] = [(d, to_minutes(s), to_minutes(e)) for d, s, e in section["meetings"]]
        section["blocked"] = {b for b in blocked if has_conflict(section, {"mins": [b]})}
        options.setdefault(section["course_code"], []).append(section)

    #required courses with no units and no time specified are still taken
    for c in req:
        if not c["units"].strip() and c["course_code"] not in options:
            options[c["course_code"]] = [{"course_code": c["course_code"], "section": "-", "time_slot": "No time allotted",
                                          "meetings": [], "mins": [], "blocked": set()}]

    req_codes = {c["course_code"] for c in req}
    opt_codes = []
    for c in spec + elec + ge:
        code = c["course_code"]
        if code not in req_codes and code not in opt_codes and options.get(code) and course_units.get(code, 0) > 0 and not code.startswith("HK "):
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
        if code.startswith("HK "):
            units_label += " (hk)"
        print(f"{code:<14} {section['section']:<10} {units_label:<7} {section['time_slot']}")

def a_star(program, specialization, year, semester, blocked_times=()):
    print("solving timetable...")
    options, course_units, req_codes, opt_codes = setup_a_star_inputs(
        program, specialization, year, semester, blocked_times
    )

    if not req_codes:
        print("no required courses found for this program/specialization.")
        return []

    missing = sorted(c for c in req_codes if not options.get(c))
    if missing:
        print(f"error: required courses have no sections: {', '.join(missing)}")
        return []

    req_units = sum(course_units.get(c, 0) for c in req_codes if not c.startswith("HK "))
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
        u = 0 if codes[i].startswith("HK ") else course_units.get(codes[i], 0)
        taken = (reach[i + 1] << u) & full
        reach[i] = taken if i < n_req else (reach[i + 1] | taken)

    def shortfall(units, next_depth):
        totals = (reach[next_depth] << units) & full
        return None if totals == 0 else MAX_UNITS - (totals.bit_length() - 1)

    #classes added later can fill at most their own minutes of the current gaps
    rest_minutes = [0] * (len(codes) + 1)
    for i in range(len(codes) - 1, -1, -1):
        rest_minutes[i] = rest_minutes[i + 1] + max(sum(e - s for _, s, e in sec["mins"]) for sec in options[codes[i]])

    def soft_cost(chosen, depth):
        #soft constraints: vacant minutes and blocked times
        gap = gap_cost(chosen)
        return SOFT_CONSTRAINT_WEIGHT * max(0, gap - rest_minutes[depth]) + blocked_cost(chosen), gap

    def show(chosen, units):
        #hard constraints are never allowed in a node
        conflicts, academic_units, missing_required = schedule_metrics(chosen, course_units, req_codes)
        if conflicts or academic_units > MAX_UNITS or missing_required:
            print("no valid schedule found in this run.")
            return []

        print_a_star_results(chosen, course_units, solve_fitness(chosen, course_units, req_codes), academic_units, nodes)
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
        code_units = 0 if code.startswith("HK ") else course_units.get(code, 0)

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