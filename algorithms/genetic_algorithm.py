import random
from helper import MAX_UNITS, load_term_data, to_minutes
from helper import chromosome_to_schedule, evaluate_schedule, fitness_from_metrics

MAXIMUM_GENERATION = 1000
POPULATION_SIZE = 100
MUTATION_RATE = 0.2

def setup_GA_inputs(program, specialization, year, semester):
    required_courses, specialized_courses, elective_courses, GE_electives, class_schedules = load_term_data(program, specialization, year, semester)
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

        if not course["units"].strip() and not has_section:
            course_units[code] = 0
            class_schedules.append({"course_code": code, "section": "-", "time_slot": "No time allotted", "meetings": []})

    all_courses = [course for course in all_courses if course["course_code"] in course_units]   # ignore unknown units

    return all_courses, required_codes, course_units, class_schedules

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

def solve_fitness(chromosome, units, required_codes, blocked_times=()):
    # same fitness as before, now computed by the shared evaluation (blocked_times must be in minutes)
    metrics = evaluate_schedule(chromosome_to_schedule(chromosome), units, required_codes, blocked_times)
    return fitness_from_metrics(metrics)

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
    # the shared code works in minutes, so convert ("M", "12:00", "12:30") -> ("M", 720, 750)
    blocked_times = [(day, to_minutes(start), to_minutes(end)) for day, start, end in blocked_times]
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
    metrics = evaluate_schedule(chromosome_to_schedule(best), course_units, required_codes, blocked_times)
 
    if metrics["valid"]:
        print_results(best, course_units, metrics["academic_units"], best_fitness)
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
