
#!/usr/bin/env python3
"""Desktop GUI (tkinter) version of the class-scheduling input form.
 
Run:  python scheduler_gui.py
No extra packages needed; tkinter ships with Python.
"""
import json
import os
import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field, asdict, replace
from tkinter import ttk, filedialog, messagebox
 
from schedule_model import (
    DAY_START_MIN, SLOT_MIN, SAMPLE_OUTPUT,
    format_result, result_from_text, section_conflicts,
)
 
# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
 
 
@dataclass
class info:
    name: str
    course: str
    specialization: str
    year: str
    semester: str
    algorithm: str
    gap: float
    availability: dict = field(default_factory=dict)  # (day, slot) -> bool
 
 
COURSES = {
    "BSCE": ["BSCE 2018 Thesis", "BSCE 2018 Innovationeering", "BSCE 2018 General"],
    "BSIE": [
        "BSIE 2018 Thesis",
        "BSIE 2018 Innovationeering",
        "BSIE 2018 Engineering Industry Research",
        "BSIE 2018 General",
    ],
    "BSABE": [
        "BSABE 2018 Agribiosystems Machinery Power Engineering Engineering Industry Research",
        "BSABE 2018 Land and Water Resources Engineering Engineering Industry Research",
        "BSABE 2018 Land and Water Resources Engineering Innovationeering",
        "BSABE 2018 Agricultural, Food and Bioprocess Engineering General", "BSABE 2018 Agribiosystems Machinery Power Engineering General", "BSABE 2018 Agricultural, Food and Bioprocess Engineering Engineering Industry Research",
        "BSABE 2018 Agribiosystems Machinery Power Engineering Thesis",
        "BSABE 2018 Agricultural, Food and Bioprocess Engineering Thesis",
        "BSABE 2018 Land and Water Resources Engineering Thesis",
        "BSABE 2018 Agrometeorology, Bio-Structures, and Environment Engineering Engineering Industry Research",
        "BSABE 2018 Agrometeorology, Bio-Structures, and Environment Engineering Thesis",
        "BSABE 2018 Agrometeorology, Bio-Structures, and Environment Engineering Innovationeering",
        "BSABE 2018 Agribiosystems Machinery Power Engineering Innovationeering",
        "BSABE 2018 Agricultural, Food and Bioprocess Engineering Innovationeering",
        "BSABE 2018 Agrometeorology, Bio-Structures, and Environment Engineering General",
        "BSABE 2018 Land and Water Resources General",
    ],
    "BSEE": [
        "BSEE 2018 Computer Engineering Innovationeering",
        "BSEE 2018 Computer Engineering Engineering Industry Research",
        "BSEE 2018 Electronics Engineering Thesis",
        "BSEE 2018 Electronics Engineering Engineering",
        "BSEE 2018 Power Engineering Innovationeering",
        "BSEE 2018 Power Engineering Engineering Industry Research",
        "BSEE 2018 Power Engineering Thesis",
        "BSEE 2018 Computer Engineering Thesis",
        "BSEE 2018 Electronics Engineering Innovationeering",
        "Bachelor of Science in Electrical Engineering",
        "BSEE 2018 Computer Engineering General",
        "BSEE 2018 Power Engineering General",
    ],
    "BSChE": [
        "BSChE 2018 Sugar Technology Engineering Industry Research",
        "BSChE 2018 Pulp and Paper Innovationeering",
        "BSChE 2018 Pulp and Paper Engineering Industry Research",
        "BSChE 2018 General Thesis",
        "BSChE 2018 General Innovationeering",
        "BSChE 2018 Sugar Technology Thesis",
        "BSChE 2018 Sugar Technology Innovationeering",
        "BSChE 2018 Pulp and Paper Thesis",
        "BSChE 2018 General Engineering Industry Research",
    ],
    "BSME": [
        "BSME 2018 Innovationeering",
        "BSME 2018 Thesis",
        "BSME 2018 Engineering Industry Research",
        "BSME 2018 General",
    ],
    "BSMatE": ["BSMatE General 2022"],
}
 
YEARS = ["1st year", "2nd year", "3rd year", "4th year"]
SEMESTERS = ["1st Semester", "2nd Semester"]
ALGORITHMS = ["Backtracking", "A*", "Genetic Algorithm"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
 
TIME_SLOTS = [
    "7-7:30 AM", "7:30-8 AM", "8-8:30 AM", "8:30-9 AM", "9-9:30 AM", "9:30-10 AM",
    "10-10:30 AM", "10:30-11 AM", "11-11:30 AM", "11:30-12 PM", "12-12:30 PM", "12:30-1 PM",
    "1-1:30 PM", "1:30-2 PM", "2-2:30 PM", "2:30-3 PM", "3-3:30 PM", "3:30-4 PM",
    "4-4:30 PM", "4:30-5 PM", "5-5:30 PM", "5:30-6 PM", "6-6:30 PM", "6:30-7 PM",
]
 
AVAILABLE_COLOR = "#d8f5d0"    # light green
UNAVAILABLE_COLOR = "#006b50"  # dark green
HEADER_BG = "#444444"
 
# ----------------------------------------------------------------------------
# Timetable widget: click or drag to paint, click a header to toggle a row/column
# ----------------------------------------------------------------------------
 
 
class TimetableGrid(tk.Canvas):
    LABEL_W = 100
    HEADER_H = 30
    CELL_W = 90
    CELL_H = 22
 
    def __init__(self, master, **kw):
        width = self.LABEL_W + self.CELL_W * len(DAYS) + 1
        height = self.HEADER_H + self.CELL_H * len(TIME_SLOTS) + 1
        super().__init__(master, width=width, height=height, highlightthickness=0, **kw)
 
        self.unavailable = {}          # (day, slot) -> bool
        self._rects = {}               # (row, col) -> canvas id
        self._paint_value = None
        self._last_cell = None
 
        self._draw()
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
 
    # -- drawing ---------------------------------------------------------
    def _draw(self):
        self.create_rectangle(0, 0, self.LABEL_W, self.HEADER_H, fill=HEADER_BG, outline="white")
        self.create_text(self.LABEL_W / 2, self.HEADER_H / 2, text="Time",
                         fill="white", font=("TkDefaultFont", 10, "bold"))
        for c, day in enumerate(DAYS):
            x0 = self.LABEL_W + c * self.CELL_W
            self.create_rectangle(x0, 0, x0 + self.CELL_W, self.HEADER_H, fill=HEADER_BG, outline="white")
            self.create_text(x0 + self.CELL_W / 2, self.HEADER_H / 2, text=day,
                             fill="white", font=("TkDefaultFont", 10, "bold"))
        for r, slot in enumerate(TIME_SLOTS):
            y0 = self.HEADER_H + r * self.CELL_H
            self.create_rectangle(0, y0, self.LABEL_W, y0 + self.CELL_H, fill=HEADER_BG, outline="white")
            self.create_text(self.LABEL_W / 2, y0 + self.CELL_H / 2, text=slot,
                             fill="white", font=("TkDefaultFont", 9))
            for c in range(len(DAYS)):
                x0 = self.LABEL_W + c * self.CELL_W
                self._rects[(r, c)] = self.create_rectangle(
                    x0, y0, x0 + self.CELL_W, y0 + self.CELL_H,
                    fill=AVAILABLE_COLOR, outline="white",
                )
 
    # -- state -----------------------------------------------------------
    def _set(self, r, c, value):
        key = (DAYS[c], TIME_SLOTS[r])
        if self.unavailable.get(key, False) == value:
            return
        self.unavailable[key] = value
        self.itemconfigure(self._rects[(r, c)], fill=UNAVAILABLE_COLOR if value else AVAILABLE_COLOR)
 
    def _get(self, r, c):
        return self.unavailable.get((DAYS[c], TIME_SLOTS[r]), False)
 
    def clear(self):
        for r in range(len(TIME_SLOTS)):
            for c in range(len(DAYS)):
                self._set(r, c, False)
 
    def count_unavailable(self):
        return sum(1 for v in self.unavailable.values() if v)
 
    # -- mouse -----------------------------------------------------------
    def _cell_at(self, x, y):
        if x < self.LABEL_W or y < self.HEADER_H:
            return None
        c = int((x - self.LABEL_W) // self.CELL_W)
        r = int((y - self.HEADER_H) // self.CELL_H)
        if 0 <= r < len(TIME_SLOTS) and 0 <= c < len(DAYS):
            return r, c
        return None
 
    def _on_press(self, e):
        cell = self._cell_at(e.x, e.y)
        if cell:
            r, c = cell
            self._paint_value = not self._get(r, c)
            self._last_cell = cell
            self._set(r, c, self._paint_value)
            return
 
        # Header click: toggle a whole column (day) or row (time)
        if e.y < self.HEADER_H and e.x >= self.LABEL_W:
            c = int((e.x - self.LABEL_W) // self.CELL_W)
            if 0 <= c < len(DAYS):
                value = not all(self._get(r, c) for r in range(len(TIME_SLOTS)))
                for r in range(len(TIME_SLOTS)):
                    self._set(r, c, value)
        elif e.x < self.LABEL_W and e.y >= self.HEADER_H:
            r = int((e.y - self.HEADER_H) // self.CELL_H)
            if 0 <= r < len(TIME_SLOTS):
                value = not all(self._get(r, c) for c in range(len(DAYS)))
                for c in range(len(DAYS)):
                    self._set(r, c, value)
        self._paint_value = None
 
    def _on_drag(self, e):
        if self._paint_value is None:
            return
        cell = self._cell_at(e.x, e.y)
        if cell and cell != self._last_cell:
            self._last_cell = cell
            self._set(*cell, self._paint_value)
 
    def _on_release(self, _e):
        self._paint_value = None
        self._last_cell = None
 
 
# ----------------------------------------------------------------------------
# Solver hook, results window, and main window
# ----------------------------------------------------------------------------
 
 
PALETTE = ["#cfe8ff", "#ffd9b3", "#d9f2d0", "#f9d1e6", "#e6dcff",
           "#fff3b0", "#c8f1ee", "#ffd0d0", "#e3e3e3", "#d5e8c8"]
BLOCKED_COLOR = "#dcdcdc"
CONFLICT_COLOR = "#b00020"
NOTE_COLOR = "#8a5a00"
 
PLACEHOLDER_NOTE = ("SAMPLE schedule (placeholder). Fill in solve() in scheduler_gui.py "
                    "to show your algorithm's result here.")
 
 
def solve(information):
    """>>> CONNECT YOUR ALGORITHM HERE <<<
 
    Receives the `info` object (information.course, .specialization, .year,
    .semester, .algorithm, .gap, .availability) and must return a
    ScheduleResult (see schedule_model.py).
 
    Easiest way, if your solver prints its result as text:
 
        from your_solver import run          # your own module
        text = run(information)              # or capture what it prints
        result = result_from_text(text)
        result.extra = {"Population size": 200, "Generations": 150}   # optional
        return result
 
    Until this is filled in, the GUI shows a sample schedule instead.
    """
    raise NotImplementedError
 
 
class ScheduleGrid(tk.Canvas):
    """Read-only timetable (same layout as the availability grid) with the
    scheduled subjects written into their time blocks."""
    LABEL_W = 100
    HEADER_H = 30
    CELL_W = 90
    CELL_H = 22
 
    def __init__(self, master, **kw):
        n = len(TIME_SLOTS)
        super().__init__(
            master, bg="white", highlightthickness=0,
            width=self.LABEL_W + self.CELL_W * len(DAYS) + 1,
            height=self.HEADER_H + self.CELL_H * n + 1, **kw)
        self.render(None, set())
 
    def _y(self, minutes):
        return self.HEADER_H + (minutes - DAY_START_MIN) / SLOT_MIN * self.CELL_H
 
    def render(self, result, blocked):
        self.delete("all")
        bold = ("TkDefaultFont", 10, "bold")
        self.create_rectangle(0, 0, self.LABEL_W, self.HEADER_H, fill=HEADER_BG, outline="white")
        self.create_text(self.LABEL_W / 2, self.HEADER_H / 2, text="Time", fill="white", font=bold)
        for c, day in enumerate(DAYS):
            x0 = self.LABEL_W + c * self.CELL_W
            self.create_rectangle(x0, 0, x0 + self.CELL_W, self.HEADER_H,
                                  fill=HEADER_BG, outline="white")
            self.create_text(x0 + self.CELL_W / 2, self.HEADER_H / 2, text=day,
                             fill="white", font=bold)
        for r, slot in enumerate(TIME_SLOTS):
            y0 = self.HEADER_H + r * self.CELL_H
            self.create_rectangle(0, y0, self.LABEL_W, y0 + self.CELL_H,
                                  fill=HEADER_BG, outline="white")
            self.create_text(self.LABEL_W / 2, y0 + self.CELL_H / 2, text=slot,
                             fill="white", font=("TkDefaultFont", 9))
            for c in range(len(DAYS)):
                x0 = self.LABEL_W + c * self.CELL_W
                self.create_rectangle(
                    x0, y0, x0 + self.CELL_W, y0 + self.CELL_H,
                    fill=BLOCKED_COLOR if (c, r) in blocked else "white", outline="#e4e4e4")
 
        if result is None:
            return
        for i, sec in enumerate(result.sections):
            color = PALETTE[i % len(PALETTE)]
            clash = bool(section_conflicts(sec, blocked))
            for m in sec.meetings:
                for d in m.days:
                    x0 = self.LABEL_W + d * self.CELL_W + 1
                    x1 = x0 + self.CELL_W - 2
                    y0, y1 = self._y(m.start) + 1, self._y(m.end) - 1
                    self.create_rectangle(x0, y0, x1, y1, fill=color,
                                          outline=CONFLICT_COLOR if clash else "#777777",
                                          width=2 if clash else 1)
                    text = f"{sec.course}\n{sec.section}" if (y1 - y0) >= 34 else sec.course
                    self.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text, justify="center",
                                     width=self.CELL_W - 8, font=("TkDefaultFont", 9))
 
 
# ----------------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------------
 
 
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Class Scheduler")
        self.information = None
        self.result = None
        self.header_text = ""
 
        self.name_var = tk.StringVar()
        self.course_var = tk.StringVar(value=list(COURSES)[0])
        self.spec_var = tk.StringVar()
        self.year_var = tk.StringVar(value=YEARS[0])
        self.sem_var = tk.StringVar(value=SEMESTERS[0])
        self.algo_var = tk.StringVar(value=ALGORITHMS[0])
        self.gap_var = tk.StringVar(value="0")
        self.status_var = tk.StringVar()
        self.fitness_var = tk.StringVar(value="-")
        self.header_var = tk.StringVar()
        self.note_var = tk.StringVar()
 
        self._build()
        self._update_specializations()
        # Placeholder so the layout is visible before anything is solved
        self._show_result(result_from_text(SAMPLE_OUTPUT), None, set(), placeholder=True)
 
    # -- layout ----------------------------------------------------------
    def _build(self):
        outer = ttk.Frame(self, padding=12)
        outer.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
 
        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="n", padx=(0, 16))
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="n")
 
        ttk.Label(left, text="About the Program", font=("TkDefaultFont", 16, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            left, wraplength=380, justify="left",
            text=("This program helps students schedule their classes for the semester. "
                  "Enter basic information, then mark the times you are NOT available."),
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 10))
 
        ttk.Label(left, text="Basic Information", font=("TkDefaultFont", 11, "bold")).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(0, 4))
 
        def row(r, label, widget):
            ttk.Label(left, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
            widget.grid(row=r, column=1, sticky="ew", pady=3)
 
        row(3, "Name:", ttk.Entry(left, textvariable=self.name_var, width=45))
        course_cb = ttk.Combobox(left, textvariable=self.course_var, values=list(COURSES),
                                 state="readonly", width=42)
        course_cb.bind("<<ComboboxSelected>>", lambda _e: self._update_specializations())
        row(4, "Course:", course_cb)
        self.spec_cb = ttk.Combobox(left, textvariable=self.spec_var, state="readonly", width=42)
        row(5, "Specialization:", self.spec_cb)
        row(6, "Year:", ttk.Combobox(left, textvariable=self.year_var, values=YEARS,
                                     state="readonly", width=42))
        row(7, "Semester:", ttk.Combobox(left, textvariable=self.sem_var, values=SEMESTERS,
                                         state="readonly", width=42))
 
        ttk.Label(left, text="Preferences", font=("TkDefaultFont", 11, "bold")).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(12, 4))
        row(9, "Algorithm:", ttk.Combobox(left, textvariable=self.algo_var, values=ALGORITHMS,
                                          state="readonly", width=42))
        row(10, "Gap (hours):", ttk.Spinbox(left, textvariable=self.gap_var, from_=0, to=12,
                                            increment=0.5, width=10))
 
        buttons = ttk.Frame(left)
        buttons.grid(row=11, column=0, columnspan=2, sticky="w", pady=(14, 4))
        self.submit_btn = ttk.Button(buttons, text="Submit & Generate Schedule", command=self.submit)
        self.submit_btn.pack(side="left")
        ttk.Button(buttons, text="Save as JSON...", command=self.save).pack(side="left", padx=6)
        ttk.Label(left, textvariable=self.status_var, foreground="#555555").grid(
            row=12, column=0, columnspan=2, sticky="w", pady=(0, 6))
 
        # Fitness value
        fit = ttk.LabelFrame(left, text="Fitness Value", padding=(10, 4))
        fit.grid(row=13, column=0, columnspan=2, sticky="ew", pady=(6, 6))
        ttk.Label(fit, textvariable=self.fitness_var,
                  font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
 
        # Test variables
        tv = ttk.LabelFrame(left, text="Test Variables", padding=(10, 6))
        tv.grid(row=14, column=0, columnspan=2, sticky="ew")
        self.tv_frame = ttk.Frame(tv)
        self.tv_frame.pack(fill="x")
 
        out_btns = ttk.Frame(left)
        out_btns.grid(row=15, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(out_btns, text="Copy result as text", command=self.copy_text).pack(side="left")
        ttk.Button(out_btns, text="Save result as text...", command=self.save_text).pack(
            side="left", padx=6)
 
        # Right side: tabs
        self.tabs = ttk.Notebook(right)
        self.tabs.grid(row=0, column=0, sticky="n")
 
        avail_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(avail_tab, text="Weekly Availability")
        ttk.Label(avail_tab, text="Click or drag to mark times you are unavailable. "
                                  "Click a day or time header to toggle the whole column/row.",
                  wraplength=640).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.grid_widget = TimetableGrid(avail_tab)
        self.grid_widget.grid(row=1, column=0, sticky="w")
        legend = ttk.Frame(avail_tab)
        legend.grid(row=2, column=0, sticky="w", pady=(6, 0))
        for color, text in ((AVAILABLE_COLOR, "Available"), (UNAVAILABLE_COLOR, "Unavailable")):
            tk.Frame(legend, width=16, height=16, bg=color, highlightbackground="gray",
                     highlightthickness=1).pack(side="left")
            ttk.Label(legend, text=text).pack(side="left", padx=(4, 12))
        ttk.Button(legend, text="Clear all", command=self.grid_widget.clear).pack(side="left")
 
        sched_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(sched_tab, text="Generated Schedule")
        ttk.Label(sched_tab, textvariable=self.header_var, wraplength=640,
                  font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(sched_tab, textvariable=self.note_var, fg=NOTE_COLOR, wraplength=640,
                 justify="left").grid(row=1, column=0, sticky="w", pady=(0, 4))
        self.schedule_grid = ScheduleGrid(sched_tab)
        self.schedule_grid.grid(row=2, column=0, sticky="w")
        ttk.Label(sched_tab, text="Gray cells = your unavailable times. "
                                  "Red outline = a subject that overlaps them.").grid(
            row=3, column=0, sticky="w", pady=(4, 0))
 
        list_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(list_tab, text="Course List")
        cols = ("course", "section", "units", "meeting")
        self.tree = ttk.Treeview(list_tab, columns=cols, show="headings", height=16)
        for col, text, width in (("course", "Course", 140), ("section", "Section", 90),
                                 ("units", "Units", 70), ("meeting", "Meeting times", 320)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w")
        self.tree.tag_configure("conflict", foreground=CONFLICT_COLOR)
        self.tree.pack(fill="both", expand=True)
 
    # -- helpers ---------------------------------------------------------
    def _update_specializations(self):
        options = COURSES[self.course_var.get()]
        self.spec_cb["values"] = options
        self.spec_var.set(options[0])
 
    def _blocked_from(self, info_obj):
        if info_obj is None:
            return set()
        return {
            (DAYS.index(d), TIME_SLOTS.index(t))
            for (d, t), ok in info_obj.availability.items() if not ok
        }
 
    def _set_test_vars(self, rows):
        for w in self.tv_frame.winfo_children():
            w.destroy()
        self.tv_frame.columnconfigure(1, weight=1)
        for r, (label, value) in enumerate(rows):
            ttk.Label(self.tv_frame, text=label + ":", foreground="#555555").grid(
                row=r, column=0, sticky="w", pady=1, padx=(0, 10))
            ttk.Label(self.tv_frame, text=str(value), font=("TkDefaultFont", 10, "bold")).grid(
                row=r, column=1, sticky="w", pady=1)
 
    # -- showing a result --------------------------------------------------
    def _show_result(self, result, info_obj, blocked, placeholder=False):
        self.result = result
        if info_obj is not None and not placeholder:
            self.header_text = (f"{info_obj.course} | {info_obj.specialization} | "
                                f"{info_obj.year} | {info_obj.semester}")
        else:
            self.header_text = result.header
        self.header_var.set(self.header_text)
        self.note_var.set(PLACEHOLDER_NOTE if placeholder else "")
 
        conflicts = [s for s in result.sections if section_conflicts(s, blocked)]
 
        # fitness
        self.fitness_var.set("-" if result.fitness is None else f"{result.fitness:.2f}")
 
        # test variables
        units = f"{result.academic_units:g}"
        if result.max_units is not None:
            units += f" / {result.max_units:g}"
        rows = [
            ("Algorithm", info_obj.algorithm if info_obj else "-"),
            ("Gap (hours)", f"{info_obj.gap:g}" if info_obj else "-"),
            ("Academic units", units),
            ("Nodes expanded", "-" if result.nodes_expanded is None else f"{result.nodes_expanded:,}"),
            ("Node limit reached", "Yes" if result.node_limit_reached else "No"),
            ("Runtime", "-" if result.runtime_sec is None else f"{result.runtime_sec:.2f} s"),
            ("Overlaps w/ unavailable", len(conflicts) if info_obj else "-"),
        ]
        rows += list(result.extra.items())
        self._set_test_vars(rows)
 
        # grid + list
        self.schedule_grid.render(result, blocked)
        self.tree.delete(*self.tree.get_children())
        for s in result.sections:
            tags = ("conflict",) if section_conflicts(s, blocked) else ()
            self.tree.insert("", "end", tags=tags,
                             values=(s.course, s.section, s.units_text(), s.meeting_text()))
 
    # -- submit & solve ----------------------------------------------------
    def submit(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Missing name", "Please enter your name.")
            return
        try:
            gap = float(self.gap_var.get())
            if gap < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid gap", "Gap must be a non-negative number.")
            return
 
        availability = {
            (day, t): not self.grid_widget.unavailable.get((day, t), False)
            for day in DAYS for t in TIME_SLOTS
        }
        self.information = info(
            name=name, course=self.course_var.get(), specialization=self.spec_var.get(),
            year=self.year_var.get(), semester=self.sem_var.get(),
            algorithm=self.algo_var.get(), gap=gap, availability=availability,
        )
        self._start_solve()
 
    def _start_solve(self):
        info_obj = self.information
        self.submit_btn.configure(state="disabled")
        self.status_var.set("Information saved. Solving timetable...")
        results = queue.Queue()
 
        def work():
            t0 = time.perf_counter()
            try:
                res = solve(info_obj)
                if res.runtime_sec is None:
                    res.runtime_sec = time.perf_counter() - t0
                results.put(("ok", res))
            except NotImplementedError:
                results.put(("sample", result_from_text(SAMPLE_OUTPUT)))
            except Exception as e:  # show solver errors instead of dying silently
                results.put(("error", e))
 
        threading.Thread(target=work, daemon=True).start()
        self._poll(results, info_obj)
 
    def _poll(self, results, info_obj):
        try:
            kind, value = results.get_nowait()
        except queue.Empty:
            self.after(100, self._poll, results, info_obj)
            return
        self.submit_btn.configure(state="normal")
        if kind == "error":
            self.status_var.set("Solver failed.")
            messagebox.showerror("Solver error", str(value))
            return
 
        blocked = self._blocked_from(info_obj)
        if kind == "sample":
            self.status_var.set("Solver not connected - showing the sample schedule.")
            self._show_result(value, info_obj, blocked, placeholder=True)
        else:
            self.status_var.set("Done.")
            self._show_result(value, info_obj, blocked)
        self.tabs.select(1)
 
    # -- exporting ---------------------------------------------------------
    def _result_text(self):
        return format_result(replace(self.result, header=self.header_text))
 
    def copy_text(self):
        self.clipboard_clear()
        self.clipboard_append(self._result_text())
        self.status_var.set("Result copied to clipboard.")
 
    def save_text(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile="schedule.txt", filetypes=[("Text", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._result_text() + "\n")
 
    def save(self):
        if self.information is None:
            messagebox.showinfo("Nothing to save", "Press Submit first.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json", initialfile="schedule_input.json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        data = asdict(self.information)
        data["availability"] = {f"{d}|{t}": v for (d, t), v in self.information.availability.items()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        messagebox.showinfo("Saved", f"Saved to {os.path.basename(path)}")
 
 
if __name__ == "__main__":
    App().mainloop()
 
 
