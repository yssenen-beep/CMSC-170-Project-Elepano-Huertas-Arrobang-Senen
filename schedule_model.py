"""Data model for a generated schedule, plus helpers to read/print it.
 
No GUI code here, so you can import it from your solver or from tests.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional
 
DAY_LABELS = ["M", "T", "W", "Th", "F", "S"]
_DAY_ALIASES = {"m": 0, "t": 1, "w": 2, "th": 3, "f": 4, "s": 5, "sa": 5}
 
DAY_START_MIN = 7 * 60    # 7:00 AM
DAY_END_MIN = 19 * 60     # 7:00 PM
SLOT_MIN = 30
 
 
def fmt_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
 
 
def parse_time(text: str) -> int:
    h, m = text.strip().split(":")
    return int(h) * 60 + int(m)
 
 
@dataclass
class Meeting:
    days: List[int]   # indexes into DAY_LABELS (0 = Monday ... 5 = Saturday)
    start: int        # minutes since midnight
    end: int
 
    def label(self) -> str:
        days = ",".join(DAY_LABELS[d] for d in self.days)
        return f"{days} {fmt_time(self.start)}-{fmt_time(self.end)}"
 
 
@dataclass
class ScheduledSection:
    course: str
    section: str
    units: float
    meetings: List[Meeting]
    hk: bool = False   # HK courses carry units but don't count as academic units
 
    @property
    def academic_units(self) -> float:
        return 0 if self.hk else self.units
 
    def units_text(self) -> str:
        u = int(self.units) if float(self.units).is_integer() else self.units
        return f"{u} (hk)" if self.hk else str(u)
 
    def meeting_text(self) -> str:
        return "; ".join(m.label() for m in self.meetings)
 
 
@dataclass
class ScheduleResult:
    sections: List[ScheduledSection] = field(default_factory=list)
    max_units: Optional[float] = None
    fitness: Optional[float] = None
    nodes_expanded: Optional[int] = None
    node_limit_reached: bool = False
    header: str = ""   # e.g. "BSChE | GENERAL | 1st year | 1st Semester"
    runtime_sec: Optional[float] = None
    # Any extra test variables you want shown in the GUI, e.g.
    # {"Population size": 200, "Generations": 150, "Mutation rate": 0.05}
    extra: dict = field(default_factory=dict)
 
    @property
    def academic_units(self) -> float:
        return sum(s.academic_units for s in self.sections)
 
 
def _num(x: float) -> str:
    return f"{x:g}"
 
 
def format_result(result: ScheduleResult) -> str:
    """Plain-text version, in the same layout your solver prints."""
    lines = []
    if result.header:
        lines.append(result.header)
    lines.append("solving timetable...")
    if result.node_limit_reached:
        lines.append("node limit reached, showing the best schedule found so far "
                     "(not guaranteed best).")
    if result.nodes_expanded is not None:
        lines.append(f"nodes expanded: {result.nodes_expanded}")
    best = f"best schedule: {_num(result.academic_units)} academic units"
    if result.max_units is not None:
        best += f" out of {_num(result.max_units)} max units"
    lines.append(best)
    if result.fitness is not None:
        lines.append(f"fitness value: {result.fitness:.2f}")
    lines.append(f"{'course':<15}{'section':<11}{'units':<8}meeting times")
    lines.append("-" * 65)
    for s in result.sections:
        lines.append(f"{s.course:<15}{s.section:<11}{s.units_text():<8}{s.meeting_text()}")
    return "\n".join(lines)
 
 
# ----------------------------------------------------------------------------
# Parsing the text your solver prints
# ----------------------------------------------------------------------------
 
_ROW_RE = re.compile(
    r"^(?P<course>.+?)\s{2,}(?P<section>\S+)\s+(?P<units>\d+(?:\.\d+)?)"
    r"(?:\s+\((?P<tag>\w+)\))?\s+(?P<meet>\S.*)$"
)
_MEET_RE = re.compile(r"^(?P<days>[A-Za-z,]+)\s+(?P<s>\d{1,2}:\d{2})-(?P<e>\d{1,2}:\d{2})$")
 
 
def _parse_meeting(text: str) -> Meeting:
    m = _MEET_RE.match(text.strip())
    if not m:
        raise ValueError(f"can't read meeting time: {text!r}")
    days = []
    for tok in m.group("days").split(","):
        key = tok.strip().lower()
        if key not in _DAY_ALIASES:
            raise ValueError(f"unknown day {tok!r} in {text!r}")
        days.append(_DAY_ALIASES[key])
    return Meeting(days, parse_time(m.group("s")), parse_time(m.group("e")))
 
 
def result_from_text(text: str) -> ScheduleResult:
    """Build a ScheduleResult from output formatted like the examples:
 
        nodes expanded: 25
        best schedule: 20 academic units out of 21 max units
        fitness value: 20.00
        course         section    units   meeting times
        ------------------------------------------------
        CHEM 18        U          3       T,Th 10:00-11:30
    """
    result = ScheduleResult()
    in_table = False
    for raw in text.splitlines():
        line = raw.rstrip()
        low = line.strip().lower()
        if not low:
            continue
        if in_table:
            m = _ROW_RE.match(line.strip())
            if not m:
                continue
            result.sections.append(ScheduledSection(
                course=m.group("course").strip(),
                section=m.group("section"),
                units=float(m.group("units")),
                meetings=[_parse_meeting(p) for p in m.group("meet").split(";")],
                hk=(m.group("tag") or "").lower() == "hk",
            ))
        elif low.startswith("course") and "section" in low:
            in_table = True
        elif low.startswith("nodes expanded"):
            result.nodes_expanded = int(re.search(r"\d+", low).group())
        elif low.startswith("best schedule"):
            m = re.search(r"out of\s+([\d.]+)", low)
            if m:
                result.max_units = float(m.group(1))
        elif low.startswith("fitness"):
            result.fitness = float(re.search(r"-?\d+(?:\.\d+)?", low).group())
        elif low.startswith("node limit reached"):
            result.node_limit_reached = True
        elif "|" in line and not result.header:
            result.header = line.strip()
    return result
 
 
# ----------------------------------------------------------------------------
# Conflicts with the student's unavailable times
# ----------------------------------------------------------------------------
 
 
def slot_index(minutes: int) -> int:
    return (minutes - DAY_START_MIN) // SLOT_MIN
 
 
def section_conflicts(section: ScheduledSection, blocked: set) -> list:
    """blocked is a set of (day_index, slot_index). Returns the overlapping ones."""
    hits = []
    for m in section.meetings:
        for d in m.days:
            for t in range(m.start, m.end, SLOT_MIN):
                if (d, slot_index(t)) in blocked:
                    hits.append((d, slot_index(t)))
    return hits
 
 
# ----------------------------------------------------------------------------
# Sample output (BSChE, 1st year, 1st sem) used for the GUI demo
# ----------------------------------------------------------------------------
 
SAMPLE_OUTPUT = """\
BSChE | GENERAL_ENGINEERING_INDUSTRY_RESEARCH | 1st year | 1st Semester
solving timetable...
nodes expanded: 25
best schedule: 20 academic units out of 21 max units
fitness value: 20.00
course         section    units   meeting times
-----------------------------------------------------------------
CHEM 18        U          3       T,Th 10:00-11:30
CHEM 18.1      10L        2       M,S 10:00-13:00
ChE 10         E          1       M 13:00-14:00
HK 11          CD2        2 (hk)  W 11:00-13:00
MATH 27        V          3       T,Th 11:30-13:00
MCB 11         ST1L       3       F 07:00-10:00
PHYS 51        EW         4       T,W,Th,F 13:00-14:00
PHYS 51.1      14L        1       F 10:00-13:00
PI 10          T1         3       T,Th 08:30-10:00
"""
