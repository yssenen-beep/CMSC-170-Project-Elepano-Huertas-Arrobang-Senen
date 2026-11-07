import csv, os, random
from itertools import combinations

BASE = "../filtered/"
MAX_UNITS = 21
MAXIMUM_GENERATION = 1000
POPULATION_SIZE = 100
MUTATION_RATE = 0.2

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
        if course["units"] != "":
            course_units[course["course_code"]] = int(course["units"])

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
# returns 1 if there is an overlapping schedule, else returns 0
# ------------------------------------------------------------------
def find_conflicts(a, b):
    for dayA, startA, endA in a["meetings"]:
        for dayB, startB, endB in b["meetings"]:
            if dayA == dayB and startA < endB and startB < endA:
                return 1

    return 0

# ------------------------------------------------------------------
# Fitness Function: solves for the total number of conflicts and units
#   returns tuple of conflict and total units
# ------------------------------------------------------------------
def solve_fitness(chromosome, units):
    scheduled = {}
    for course_code, section in chromosome.items():
        if section:
            scheduled[course_code] = section

    conflicts = 0
    for a, b in combinations(scheduled.values(), 2):
        conflicts += find_conflicts(a, b)

    academic_units = sum(units[course_code] for course_code in scheduled if not course_code.startswith("HK "))
    excess_units = max(0, academic_units - MAX_UNITS)
    return (-conflicts, -excess_units, academic_units)

# ------------------------------------------------------------------
# Selection: selects a parent by randomly picking candidates, then
#   returns the candidate with least conflicts. 
#       if tied, prioritize more units
# ------------------------------------------------------------------
def select_parents(population, course_units):
    candidates = random.sample(population, 3)

    return max(candidates, key=lambda chromosome: solve_fitness(chromosome, course_units))

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
def print_results(schedule, course_units, academic_units):
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

def genetic_algorithm(program, specialization, year, semester):
    print("Solving timetable...")
    all_courses, required_codes, course_units, class_schedules = setup_GA_inputs(program, specialization, year, semester)

    # INITIALIZATION (create initial population)
    population = create_initial_population(all_courses, class_schedules)

    for i in range(MAXIMUM_GENERATION):
        best = max(population, key=lambda chromosome: solve_fitness(chromosome, course_units))
        next_generation = [best]    # carry over the fittest from the current population

        while len(next_generation) < POPULATION_SIZE:
            # TOURNAMENT SELECTION
            parentA = select_parents(population, course_units)
            parentB = select_parents(population, course_units)

            # CROSSOVER
            child = crossover(parentA, parentB)

            # MUTATION
            child = mutate(child, class_schedules, required_codes)

            next_generation.append(child)

        population = next_generation    # go to the next generation

    # RESULT
    best = max(population, key=lambda chromosome: solve_fitness(chromosome, course_units))
    conflict_score, overload_score, academic_units = solve_fitness(best, course_units)

    if conflict_score == 0 and overload_score == 0:
        print_results(best, course_units, academic_units)
    else:
        print("No conflict-free schedule found in this run.")

if __name__ == "__main__":
    test_cases = [
        ("BSChE", "GENERAL_ENGINEERING_INDUSTRY_RESEARCH", "1st year", "1st Semester"),
        ("BSCE", "GENERAL", "3rd year", "2nd Semester"),
        ("BSEE", "COMPUTER_ENGG_GENERAL", "1st year", "1st Semester"),
    ]

    for case in test_cases:
        print("\n" + " | ".join(case))
        genetic_algorithm(*case)