# CMSC 170: Course Scheduling

Course scheduling with **Backtracking, A*, and Genetic Algorithm**, by Elepano, Huertas, Arrobang, and Senen.

## Project page

The static project page in `docs/` shows comparison graphs, a results table, a short method comparison, and a weekly timetable like the desktop UI. Choose a scenario, method, and run to inspect the actual output. No frontend dependencies or build step are required. Full benchmark data remains in `docs/data/`.

Preview from the repository root:

```powershell
python -m http.server 8000 --directory docs --bind 127.0.0.1
```

Open <http://127.0.0.1:8000>. Use HTTP rather than opening `index.html` directly, because the page fetches its local results JSON.

### Publish on GitHub Pages

1. Commit and push `docs/`, `scripts/`, and this README to the repository's `pages` branch.
2. In GitHub, open **Settings → Pages → Build and deployment**.
3. Choose **Deploy from a branch**, select **pages** and **/docs**, then **Save**.
4. Wait for the Pages deployment to finish. Future pushes to `pages` update the page.

If Pages is configured to use **/(root)** instead, the root `index.html` opens the project screen in `docs/` automatically, rather than displaying this README.

Expected URL after enabling Pages:

<https://yssenen-beep.github.io/CMSC-170-Project-Elepano-Huertas-Arrobang-Senen/>

This is a static research page. The Python/Tkinter scheduler runs locally; GitHub Pages does not run it.

## Reproduce the measurements

Python 3.10+; benchmark and page checks use the standard library only:

```powershell
python scripts/benchmark.py
python scripts/check_project_page.py
```

Defaults match the current solver budgets: GA 1,000 generations, population 100, mutation rate 0.2; Backtracking/A* 100,000 nodes. Each of six cases is run three times with seeds 0, 1, and 2 (54 runs). Attempts are sequential, in isolated subprocesses, with `PYTHONHASHSEED=0` and a 60-second wall-clock limit. The recorded solver runtime includes data loading and adapter parsing, excludes subprocess startup and post-run evaluation, and has no discarded warm-up. Timeouts are recorded at the configured cap and counted as unsuccessful attempts.

For a faster exploratory run, explicitly change the profile:

```powershell
python scripts/benchmark.py --generations 100 --population 50
```

This overwrites `docs/data/results.json` and `docs/data/results.csv`. Commit both files together; the page derives charts and summaries from them. JSON includes every returned schedule, run metadata, failure messages, and input/source SHA-256 hashes. The benchmark changes GA settings only in its own worker processes; application files are untouched.

### Comparison limits

- Results cover BSCE GENERAL Year 1 / Semester 1 with no preferences, unavailable hours, 30-minute target gaps, 60-minute target gaps, and 120-minute target gaps plus unavailable hours; and BSME GENERAL Year 4 / Semester 2 with no preferences. They are a small selected sample, not all programs or all difficulties.
- Backtracking searches term-listed courses. A*/GA can add courses from broader elective/specialization pools. Backtracking's preference objective and early stopping also differ. The page compares existing implementations, not algorithms constrained to identical search spaces.
- A single shared evaluator checks conflicts, missing common required courses, academic/non-academic unit caps, gap minutes, and blocked 30-minute intervals. It does not validate all elective-pool rules or prerequisites. UI fitness is not used.
- Shared fitness is `academic_units - 1000 * (conflicts + excess_units + missing_required) - 0.01 * gap_minutes - blocked_count`. Blocked hours are soft preferences. Like the desktop UI, only Backtracking uses target gaps; A*/GA always minimize gaps. The algorithms are unchanged.
- Average gap includes every pair of consecutive same-day classes, including zero-minute gaps. Target error is the mean absolute difference between these gaps and the requested gap. Both are undefined if there are no adjacent classes; target error is also undefined when no target is set. Summary values are medians across valid runs. Common fitness continues to minimize total gaps, rather than measuring target-gap satisfaction.
- Timetables show Monday–Saturday, 07:00–19:00, in 30-minute slots, using the desktop UI's course colors, gray unavailable cells, and red outlines on courses that overlap unavailable hours. Each timetable is one actual measured run, not a synthetic median schedule. The course list includes meetings without fixed times.
- Runtime includes all attempts; summary quality metrics use valid outputs only. Deterministic methods are repeated for timing variation. Three GA seeds are insufficient for broad statistical conclusions. Nodes and generations are not equivalent work units.

## Run the desktop application

```powershell
python ui.py
```

Keep the `filtered/` data folder alongside the Python source. The interface uses Tkinter, which must be available in your Python installation.
