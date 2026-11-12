import csv, os, random
from itertools import combinations
from datetime import datetime

BASE = "../filtered/"
MAX_UNITS = 21
MAXIMUM_GENERATION = 1000
POPULATION_SIZE = 100
MUTATION_RATE = 0.2
HARD_CONSTRAINT_WEIGHT = 1000
SOFT_CONSTRAINT_WEIGHT = 0.01

# ------------------------------------------------------------------
# assign the time slots for each meeting, and
#   returns a list of tuples for the meetings (day, start, end)
# ------------------------------------------------------------------
def parse_timeslot(time_slot):
    if not time_slot.strip():
        return []

    meetings = []
    meeting_split = time_slot.split(";")
    for time in meeting_split:
        days, time_range = time.split()
        start, end = time_range.split("-")

        for day in days.split(","):
            meetings.append((day, start, end))

    return meetings

# ------------------------------------------------------------------
# filters dataset according to the user constraints, and 
#   returns the list of required, specialized, elective courses, 
#   GE electives, and available class schedules 
# ------------------------------------------------------------------
def handle_file(program, specialization, year, semester):
    year_dict = {
        "1st year": "1",
        "2nd year": "2",
        "3rd year": "3",
        "4th year": "4"
    }

    semester_dict = {
        "1st Semester": "1",
        "2nd Semester": "2"
    }

    for filename in os.listdir(BASE):
        file_path = os.path.join(BASE, filename)

        if filename == "ceat_program_courses.csv":
            with open(file_path, "r", encoding='utf-8') as file:
                courses = list(csv.DictReader(file))

                required_courses = []
                specialized_courses = []
                elective_courses = []
                GE_electives = []

                # create list of required courses and GE electives
                for row in courses:
                    if row["program"] != program or row["specialization"] != specialization:
                        continue

                    if row["course_type"] == "SPECIALIZED":
                        specialized_courses.append(row)

                    elif row["course_type"] == "GE ELECTIVE":
                        GE_electives.append(row)

                    elif row["is_elective"] == "Yes":
                        elective_courses.append(row)

                    elif row["year"] == year_dict[year] and row["semester"] == semester_dict[semester]:
                        required_courses.append(row)

                # create list of schedules
                sched_fname = "ceat_class_schedule_1st_sem.csv" if semester_dict[semester] == "1" else "ceat_class_schedule_2nd_sem.csv"
                all_courses = (required_courses + specialized_courses + elective_courses + GE_electives)
                course_codes = {row["course_code"] for row in all_courses}

                sched_path = os.path.join(BASE, sched_fname)
                with open(sched_path, "r", encoding='utf-8') as sched_file:
                    available_classes = csv.DictReader(sched_file)
                    class_schedules = [row for row in available_classes if row["course_code"] in course_codes]

    # add parsed timeslots
    for section in class_schedules:
        section["meetings"] = parse_timeslot(section["time_slot"])
        
    return required_courses, specialized_courses, elective_courses, GE_electives, class_schedules

# ------------------------------------------------------------------
# sets up data structures to be used for the GA
# ------------------------------------------------------------------
def setup_GA_inputs(program, specialization, year, semester):
    required_courses, specialized_courses, elective_courses, GE_electives, class_schedules = handle_file(program, specialization, year, semester)
    
    all_courses = (required_courses + specialized_courses + elective_courses + GE_electives)

    required_codes = {course["course_code"] for course in required_courses}

    course_units = {}
    for course in all_courses:
        code = course["course_code"]
        raw_units = course["units"].strip()

        if raw_units:
            course_units[code] = int(raw_units)
        else:
            course_units[code] = 0

    timed_sections = []
    for section in class_schedules:
        if section["meetings"]:
            timed_sections.append(section)

    class_schedules = timed_sections
    
    for course in required_courses:
        code = course["course_code"]
        has_section = False
        for section in class_schedules:
            if section["course_code"] == code:
                has_section = True
                break

        # for subjects with no units and time specified
        if not course["units"].strip() and not has_section:
            course_units[code] = 0
            class_schedules.append({"course_code": code, "section": "-", "time_slot": "No time allotted", "meetings": []})

    all_courses = [course for course in all_courses if course["course_code"] in course_units]   # ignore unknown units

    return all_courses, required_codes, course_units, class_schedules

# ------------------------------------------------------------------
# Initialization: creates the initial population consisting of N chromosomes/individuals
# ------------------------------------------------------------------
def create_initial_population(courses, class_schedules):
    options = {course["course_code"]: [] for course in courses}
    for section in class_schedules:
        code = section["course_code"]
        if code in options:
            options[code].append(section)
    
    population = []
    for i in range(POPULATION_SIZE):
        chromosome = {}
        for code, sections in options.items():
            if sections:
                chromosome[code] = random.choice(sections)
            else:
                chromosome[code] = None
        
        population.append(chromosome)

    return population

# ------------------------------------------------------------------
# merges overlapping or adjacent time intervals
# ------------------------------------------------------------------
def merge_intervals(time_intervals):
    merged = []

    for start, end in sorted(time_intervals):
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))

    return merged

# ------------------------------------------------------------------
# measures gaps(vacant times) and occupied preference blocks
# ------------------------------------------------------------------
def soft_constraints(chromosome, blocked_times):
    meetings_by_day = {}
    blocked_count = 0

    for section in chromosome.values():
        if section is None:
            continue

        for day, start, end in section["meetings"]:
            if day not in meetings_by_day:
                meetings_by_day[day] = []

            meetings_by_day[day].append((start, end))

    # count each preferred vacant block at most once
    for block in set(blocked_times):
        blocked_section = {"meetings": [block]}

        for section in chromosome.values():
            if section is not None and find_conflicts(section, blocked_section):
                blocked_count += 1
                break

    gap_minutes = 0
    for intervals in meetings_by_day.values():
        meetings = merge_intervals(intervals)

        for index in range(1, len(meetings)):
            previous_end = datetime.strptime(meetings[index - 1][1], "%H:%M")
            next_start = datetime.strptime(meetings[index][0], "%H:%M")
            gap_minutes += (next_start - previous_end).total_seconds() / 60

    return gap_minutes, blocked_count

# ------------------------------------------------------------------
# returns 1 if there is an overlapping schedule, else returns 0
# ------------------------------------------------------------------
def find_conflicts(a, b):
    for dayA, startA, endA in a["meetings"]:
        for dayB, startB, endB in b["meetings"]:
            if dayA == dayB and startA < endB and startB < endA:
                return 1

    return 0

# ------------------------------------------------------------------
# counts conflicts, units, and missing required courses
# ------------------------------------------------------------------
def schedule_metrics(chromosome, units, required_codes):
    scheduled = {}
    for code, section in chromosome.items():
        if section is not None:
            scheduled[code] = section

    conflicts = 0
    for first, second in combinations(scheduled.values(), 2):
        conflicts += find_conflicts(first, second)

    academic_units = 0
    for code in scheduled:
        if not code.startswith("HK "):
            academic_units += units[code]

    missing_required = 0
    for code in required_codes:
        if code not in scheduled:
            missing_required += 1

    return conflicts, academic_units, missing_required

# ------------------------------------------------------------------
# Fitness Function: solves for the total number of conflicts and units
#   returns tuple of conflict and total units
# ------------------------------------------------------------------
def solve_fitness(chromosome, units, required_codes, blocked_times=()):
    conflicts, academic_units, missing_required = schedule_metrics(chromosome, units, required_codes)

    excess_units = max(0, academic_units - MAX_UNITS)
    gap_minutes, blocked_count = soft_constraints(chromosome, blocked_times)

    fitness_function = academic_units - HARD_CONSTRAINT_WEIGHT * (conflicts + excess_units + missing_required) - SOFT_CONSTRAINT_WEIGHT * gap_minutes - blocked_count
    return fitness_function

# ------------------------------------------------------------------
# Selection: selects a parent by randomly picking candidates, then
#   returns the candidate with least conflicts. 
#       if tied, prioritize more units
# ------------------------------------------------------------------
def select_parents(population, course_units, required_codes, blocked_times=()):
    candidates = random.sample(population, 3)

    return max(candidates, key=lambda chromosome: solve_fitness(chromosome, course_units, required_codes, blocked_times))

# ------------------------------------------------------------------
# Crossover: randomly copying classes from either parents
# ------------------------------------------------------------------
def crossover(parentA, parentB):
    child = {}
    for course_code in parentA:
        child[course_code] = random.choice((parentA[course_code], parentB[course_code]))

    return child

# ------------------------------------------------------------------
# Mutation: allows a chance to pick a course and change its section or drop it
# ------------------------------------------------------------------
def mutate(child, class_schedules, required_codes):
    if random.random() >= MUTATION_RATE:
        return child
    
    course_code = random.choice(list(child))
    current = child[course_code]

    options = []
    for section in class_schedules:
        if section["course_code"] == course_code and section != current:
            options.append(section)
    
    if course_code not in required_codes:
        options.append(None)    # added option to drop the class if it is not required

    if options:
        child[course_code] = random.choice(options)

    return child

# ------------------------------------------------------------------
# prints the results from the GA
# ------------------------------------------------------------------
def print_results(schedule, course_units, academic_units, best_fitness):
    print(f"Maximum Generation: {MAXIMUM_GENERATION}")
    print(f"Population Size: {POPULATION_SIZE}")
    print(f"Mutation Rate: {MUTATION_RATE}")
    print(f"Best schedule: {academic_units} academic units out of {MAX_UNITS} max units ")
    print(f"{'Course':<14} {'Section':<10} {'Units':<7} Meeting times")
    print("-" * 65)

    for course_code, section in sorted(schedule.items()):
        if section is None:
            continue

        units_label = str(course_units[course_code])
        if course_code.startswith("HK "):
            units_label += " (HK)"

        print(
            f"{course_code:<14} {section['section']:<10} "
            f"{units_label:<7} {section['time_slot']}"
        )

    print(f"\nFitness Value: {best_fitness}")

# ------------------------------------------------------------------
# GENETIC ALGORITHM
# ------------------------------------------------------------------
def genetic_algorithm(program, specialization, year, semester, blocked_times=()):
    print("Solving timetable...")
    all_courses, required_codes, course_units, class_schedules = setup_GA_inputs(program, specialization, year, semester)

    # INITIALIZATION (create initial population)
    population = create_initial_population(all_courses, class_schedules)

    for i in range(MAXIMUM_GENERATION):
        best = max(population, key=lambda chromosome: solve_fitness(chromosome, course_units, required_codes, blocked_times))
        next_generation = [best]    # carry over the fittest from the current population

        while len(next_generation) < POPULATION_SIZE:
            # TOURNAMENT SELECTION
            parentA = select_parents(population, course_units, required_codes, blocked_times)
            parentB = select_parents(population, course_units, required_codes, blocked_times)

            # CROSSOVER
            child = crossover(parentA, parentB)

            # MUTATION
            child = mutate(child, class_schedules, required_codes)

            next_generation.append(child)

        population = next_generation    # go to the next generation

    # RESULT
    best = max(population, key=lambda chromosome: solve_fitness(chromosome, course_units, required_codes, blocked_times))
    best_fitness = solve_fitness(best, course_units, required_codes, blocked_times)
    conflicts, academic_units, missing_required = schedule_metrics(best, course_units, required_codes)
 
    if conflicts == 0 and academic_units <= MAX_UNITS and missing_required == 0:
        print_results(best, course_units, academic_units, best_fitness)
    else:
        print("No valid schedule found in this run.")

if __name__ == "__main__":
    blocked_times = [
        ("M", "12:00", "12:30"),
        ("M", "12:30", "13:00"),
    ]
    
    test_cases = [
        ("BSEE", "POWER_ENGINEERING_INDUSTRY_RESEARCH", "4th year", "2nd Semester", blocked_times),
        ("BSME", "GENERAL", "3rd year", "1st Semester", [])
    ]

    for program, specialization, year, semester, blocks in test_cases:
        genetic_algorithm(program, specialization, year, semester, blocks)