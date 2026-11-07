import csv
import os
import heapq
from itertools import count

BASE = "../filtered/"
MAX_UNITS = 21
MAXIMUM_NODES = 100000
SLOT_MINUTES = 30
DAY_START = 7 * 60  #7:00 am start
UNIT_WEIGHT = 1.0   #penalty scale per unit under max limit
DAY_CODES = {
    "Monday": "M", "Tuesday": "T", "Wednesday": "W",
    "Thursday": "Th", "Friday": "F", "Saturday": "S"
}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
TIME_SLOTS = [
    "7-7:30 AM", "7:30-8 AM", "8-8:30 AM", "8:30-9 AM", "9-9:30 AM", "9:30-10 AM",
    "10-10:30 AM", "10:30-11 AM", "11-11:30 AM", "11:30-12 PM", "12-12:30 PM", "12:30-1 PM",
    "1-1:30 PM", "1:30-2 PM", "2-2:30 PM", "2:30-3 PM", "3-3:30 PM", "3:30-4 PM",
    "4-4:30 PM", "4:30-5 PM", "5-5:30 PM", "5:30-6 PM", "6-6:30 PM", "6:30-7 PM"
]

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

def get_blocked_slots(availability, time_slots):
    #extract set of (day_code, slot_index) marked unavailable by the user
    blocked = set()
    for (day, label), is_free in (availability or {}).items():
        if not is_free and label in time_slots:
            blocked.add((DAY_CODES.get(day, day), time_slots.index(label)))
    return blocked

def touches_blocked_slot(section, blocked):
    #check if any part of a section falls within a user-blocked slot
    for day, start, end in section["mins"]:
        for minute in range(start, end, SLOT_MINUTES):
            if (day, (minute - DAY_START) // SLOT_MINUTES) in blocked:
                return True
    return False

def has_conflict(a, b):
    #check for time overlap between two class sections
    for dayA, startA, endA in a["mins"]:
        for dayB, startB, endB in b["mins"]:
            if dayA == dayB and startA < endB and startB < endA:
                return True
    return False

def gap_cost(sections, gap):
    #calculate penalty for breaks shorter than the preferred gap
    if not gap:
        return 0.0

    by_day = {}
    for s in sections:
        for day, start, end in s["mins"]:
            by_day.setdefault(day, []).append((start, end))

    cost = 0.0
    for meetings in by_day.values():
        meetings.sort()
        for (_, end), (start, _) in zip(meetings, meetings[1:]):
            cost += max(0, gap * 60 - (start - end)) / SLOT_MINUTES
    return cost

def setup_a_star_inputs(program, specialization, year, semester, availability, time_slots):
    req, spec, elec, ge, schedules = handle_file(program, specialization, year, semester)
    blocked = get_blocked_slots(availability, time_slots)

    course_units = {}
    for c in req + spec + elec + ge:
        try:
            course_units[c["course_code"]] = int(float(c["units"]))
        except (ValueError, TypeError):
            pass

    options = {}
    for section in schedules:
        section["mins"] = [(d, to_minutes(s), to_minutes(e)) for d, s, e in section["meetings"]]
        if not touches_blocked_slot(section, blocked):
            options.setdefault(section["course_code"], []).append(section)

    req_codes = {c["course_code"] for c in req}
    opt_codes = []
    for c in spec + elec + ge:
        code = c["course_code"]
        if code not in req_codes and code not in opt_codes and options.get(code) and course_units.get(code, 0) > 0 and not code.startswith("HK "):
            opt_codes.append(code)

    return options, course_units, req_codes, opt_codes

def print_a_star_results(schedule, course_units, gap_penalty, academic_units, nodes):
    print(f"nodes expanded: {nodes}")
    print(f"best schedule: {academic_units} academic units out of {MAX_UNITS} max units")
    print(f"gap penalty: {gap_penalty:.1f}")
    print(f"{'course':<14} {'section':<10} {'units':<7} meeting times")
    print("-" * 65)

    for section in sorted(schedule, key=lambda s: s["course_code"]):
        code = section["course_code"]
        units_label = str(course_units.get(code, 0))
        if code.startswith("HK "):
            units_label += " (hk)"
        print(f"{code:<14} {section['section']:<10} {units_label:<7} {section['time_slot']}")

def a_star(program, specialization, year, semester, availability=None, gap=0, time_slots=None):
    print("solving timetable...")
    options, course_units, req_codes, opt_codes = setup_a_star_inputs(
        program, specialization, year, semester, availability, time_slots or TIME_SLOTS
    )

    if not req_codes:
        print("no required courses found for this program/specialization.")
        return []

    missing = sorted(c for c in req_codes if not options.get(c))
    if missing:
        print(f"error: required courses missing or fully blocked: {', '.join(missing)}")
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

    tie = count()
    frontier = [(0.0, 0, next(tie), 0, (), 0)]
    nodes = 0

    while frontier and nodes < MAXIMUM_NODES:
        f, _, _, depth, chosen, units = heapq.heappop(frontier)
        nodes += 1

        if depth == len(codes):
            print_a_star_results(chosen, course_units, gap_cost(chosen, gap), units, nodes)
            return list(chosen)

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
                g = gap_cost(new_chosen, gap)
                h = UNIT_WEIGHT * short
                heapq.heappush(frontier, (g + h, -(depth + 1), next(tie), depth + 1, new_chosen, new_units))

        #option 2: skip course (only allowed for optional/elective courses)
        if depth >= n_req:
            short = shortfall(units, depth + 1)
            if short is not None:
                g = gap_cost(chosen, gap)
                h = UNIT_WEIGHT * short
                heapq.heappush(frontier, (g + h, -(depth + 1), next(tie), depth + 1, chosen, units))

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