"""ZYWtool - Recording operations dashboard. UI refresh; processing stays in zyw_core.
ZYWtool contributors"""
import json
import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

HERE = (os.environ.get("ZYWTOOL_HOME") or
        (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)
if getattr(sys, "frozen", False):
    os.environ["ZYWTOOL_HOME"] = HERE
import zyw_core as core  # noqa: E402
import handcheck  # noqa: E402
import jobs  # noqa: E402

BG = "#F3F4F6"
SURFACE = "#FFFFFF"
INK = "#17191D"
MUTED = "#777D87"
LINE = "#E6E8EC"
DARK = "#111317"
ACCENT = "#B9F36A"
GREEN = "#23845B"
AMBER = "#B7791F"
RED = "#C44949"


def fmt_hms(seconds):
    s = int(round(seconds))
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


class App:
    def __init__(self, root):
        self.root = root
        root.title(f"ZYWtool | Recording Operations | {core.CREDIT}")
        root.geometry("1440x900")
        root.minsize(1120, 720)
        root.configure(bg=BG)
        self.cfg = core.load_config()
        self.sessions, self.view, self.by_name = [], [], {}
        self._setup_style()
        self._build_shell()
        self._pill_jobs = False
        self.jobs = jobs.JobManager(root, on_change=self._jobs_changed)
        self._build_dashboard()
        self.root.bind("<Control-r>", lambda _e: self.scan())
        self.root.bind("<Control-f>", lambda _e: self.sess_from_entry.focus_set())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                        foreground=INK, rowheight=34, borderwidth=0,
                        font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#F7F8FA", foreground="#555B65",
                        relief="flat", borderwidth=0, font=("Segoe UI Semibold", 9), padding=(8, 10))
        style.map("Treeview", background=[("selected", "#E9F4DB")],
                  foreground=[("selected", INK)])
        style.configure("Vertical.TScrollbar", background="#E5E7EB", troughcolor=SURFACE,
                        bordercolor=SURFACE, arrowcolor=MUTED)
        style.configure("TCombobox", padding=7, fieldbackground=SURFACE,
                        background=SURFACE, foreground=INK)
        style.configure("TEntry", padding=8, fieldbackground=SURFACE)

    def _build_shell(self):
        self.sidebar = tk.Frame(self.root, bg=DARK, width=224)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        brand = tk.Frame(self.sidebar, bg=DARK)
        brand.pack(fill="x", padx=22, pady=(27, 34))
        tk.Label(brand, text="ZYW", bg=DARK, fg="white",
                 font=("Segoe UI Black", 25)).pack(anchor="w")
        tk.Label(brand, text="RECORDING OPERATIONS", bg=DARK, fg="#8D929B",
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(1, 0))
        tk.Frame(self.sidebar, bg="#30343B", height=1).pack(fill="x", padx=18, pady=(0, 22))
        self._nav("OVERVIEW", active=True)
        self._nav("SESSION EXPLORER", command=lambda: self.tree.focus_set())
        self._nav("FOLDER TOOLS", command=self.stats_folder)
        self._nav("REPORTS & EXPORT", command=self.export)
        tk.Frame(self.sidebar, bg="#30343B", height=1).pack(fill="x", padx=18, pady=22)
        self._nav("PREFERENCES", command=self.open_settings)
        bottom = tk.Frame(self.sidebar, bg=DARK)
        bottom.pack(side="bottom", fill="x", padx=20, pady=22)
        tk.Label(bottom, text="LOCAL WORKSPACE", bg=DARK, fg="#8D929B",
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")
        tk.Label(bottom, text="MCAP 鈥?ZY WHITE", bg=DARK, fg="#D9DCE1",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(5, 0))
        tk.Label(bottom, text=core.CREDIT, bg=DARK, fg="#8D929B", font=("Segoe UI", 8),
                 wraplength=180, justify="left").pack(anchor="w", pady=(14, 0))

        self.main = tk.Frame(self.root, bg=BG)
        self.main.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(self.main, bg=BG, highlightthickness=0)
        self.scroll = ttk.Scrollbar(self.main, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=BG)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.canvas_window, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _jobs_changed(self):
        n = len(self.jobs.running())
        if n:
            self._pill_jobs = True
            self.status(f"{n} job{'s' if n > 1 else ''} running")
        elif self._pill_jobs:
            self._pill_jobs = False
            self.status("Ready", "ready")

    def _on_close(self):
        running = self.jobs.running()
        if running and not messagebox.askyesno(
                "ZYWtool", f"Ada {len(running)} proses berjalan di latar belakang.\nHentikan semua dan keluar?"):
            return
        self.jobs.stop_all()
        self.root.destroy()

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _nav(self, label, active=False, command=None):
        bg = "#292D34" if active else DARK
        fg = ACCENT if active else "#B6BBC4"
        b = tk.Button(self.sidebar, text=("鈼?  " if active else "     ") + label,
                      command=command or (lambda: None), anchor="w", relief="flat",
                      bg=bg, fg=fg, activebackground="#292D34", activeforeground="white",
                      font=("Segoe UI", 9, "bold"), padx=17, pady=13, cursor="hand2", bd=0)
        b.pack(fill="x", padx=12, pady=3)

    def _card(self, parent, padx=0, pady=0):
        f = tk.Frame(parent, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
        f.pack(fill="both", expand=True, padx=padx, pady=pady)
        return f

    def _section_title(self, parent, title, subtitle=None):
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", padx=28, pady=(24, 15))
        tk.Label(head, text=title, bg=BG, fg=INK,
                 font=("Segoe UI Semibold", 23)).pack(anchor="w")
        if subtitle:
            tk.Label(head, text=subtitle, bg=BG, fg=MUTED,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))
        return head

    def _build_dashboard(self):
        header = tk.Frame(self.content, bg=BG)
        header.pack(fill="x", padx=28, pady=(24, 8))
        left = tk.Frame(header, bg=BG)
        left.pack(side="left")
        tk.Label(left, text="Recording overview", bg=BG, fg=INK,
                 font=("Segoe UI Semibold", 22)).pack(anchor="w")
        tk.Label(left, text="Inspect sessions, validate MCAP data, and prepare operational reports.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))
        self.status_pill = tk.Label(header, text="鈼? READY", bg="#E7F3E9", fg=GREEN,
                                    font=("Segoe UI", 8, "bold"), padx=13, pady=8)
        self.status_pill.pack(side="right", pady=5)

        source = self._card(self.content)
        source.pack(fill="x", padx=28, pady=(14, 12))
        row = tk.Frame(source, bg=SURFACE)
        row.pack(fill="x", padx=18, pady=(14, 7))
        tk.Label(row, text="DATA SOURCE", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Label(row, text="Choose the recording root folder to inspect", bg=SURFACE,
                 fg="#969BA4", font=("Segoe UI", 8)).pack(side="right")
        controls = tk.Frame(source, bg=SURFACE)
        controls.pack(fill="x", padx=18, pady=(4, 16))
        self.path_var = tk.StringVar(value=self.cfg.get("data_root", ""))
        self.path_entry = ttk.Entry(controls, textvariable=self.path_var)
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self._button(controls, "Browse", self.browse, dark=False).pack(side="left", padx=(8, 16))
        self.mode_var = tk.StringVar(value=self.cfg.get("check_mode", "quick"))
        ttk.Combobox(controls, textvariable=self.mode_var, values=["quick", "full"],
                     width=9, state="readonly").pack(side="left", padx=(0, 10), ipady=3)
        self.hand_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Hand check (slow)", variable=self.hand_var).pack(
            side="left", padx=(0, 12))
        self.scan_btn = self._button(controls, "RUN SCAN  鈫?, self.scan, dark=True)
        self.scan_btn.pack(side="left")

        metrics = tk.Frame(self.content, bg=BG)
        metrics.pack(fill="x", padx=24, pady=(0, 12))
        self.metric_vars = {}
        metric_defs = [("SESSIONS", "sessions", "鈥?, "Total discovered"),
                       ("QUALIFIED", "qualified", "鈥?, "OK + warning"),
                       ("TOTAL STORAGE", "storage", "鈥?, "Combined file size"),
                       ("RECORDING TIME", "duration", "鈥?, "Combined duration")]
        for title, key, value, hint in metric_defs:
            card = tk.Frame(metrics, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
            card.pack(side="left", fill="both", expand=True, padx=4)
            tk.Label(card, text=title, bg=SURFACE, fg=MUTED,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=15, pady=(13, 5))
            var = tk.StringVar(value=value)
            self.metric_vars[key] = var
            tk.Label(card, textvariable=var, bg=SURFACE, fg=INK,
                     font=("Segoe UI Semibold", 21)).pack(anchor="w", padx=15)
            tk.Label(card, text=hint, bg=SURFACE, fg="#969BA4",
                     font=("Segoe UI", 8)).pack(anchor="w", padx=15, pady=(2, 13))

        filter_card = self._card(self.content)
        filter_card.pack(fill="x", padx=28, pady=(0, 12))
        fhead = tk.Frame(filter_card, bg=SURFACE)
        fhead.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(fhead, text="SESSION FILTERS", bg=SURFACE, fg=INK,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        self.filter_count = tk.StringVar(value="No scan data")
        tk.Label(fhead, textvariable=self.filter_count, bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 8)).pack(side="right")
        filters = tk.Frame(filter_card, bg=SURFACE)
        filters.pack(fill="x", padx=16, pady=(5, 14))
        self.sess_from = tk.StringVar(); self.sess_to = tk.StringVar()
        self.time_from = tk.StringVar(); self.time_to = tk.StringVar()
        self.shift_var = tk.StringVar(value="(semua)")
        self.sess_from_entry = self._filter_field(filters, "SESSION FROM", self.sess_from, 8)
        self.sess_to_entry = self._filter_field(filters, "TO", self.sess_to, 8)
        self._filter_field(filters, "START TIME FROM", self.time_from, 10)
        self._filter_field(filters, "TO", self.time_to, 10)
        tk.Label(filters, text="SHIFT", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 7, "bold")).pack(side="left", padx=(10, 4), anchor="s")
        self.shift_box = ttk.Combobox(filters, textvariable=self.shift_var, width=20, state="readonly")
        self.shift_box.pack(side="left", padx=(0, 10), ipady=3, anchor="s")
        self._button(filters, "APPLY", self.refresh, dark=True).pack(side="left", anchor="s")
        self._button(filters, "RESET", self.reset_filters, dark=False).pack(side="left", padx=(6, 0), anchor="s")

        table_card = self._card(self.content)
        table_card.pack(fill="both", expand=True, padx=28, pady=(0, 12))
        table_head = tk.Frame(table_card, bg=SURFACE)
        table_head.pack(fill="x", padx=16, pady=(13, 9))
        tk.Label(table_head, text="SESSION EXPLORER", bg=SURFACE, fg=INK,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self.table_count = tk.StringVar(value="0 RECORDS")
        tk.Label(table_head, textvariable=self.table_count, bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(side="right")
        table_wrap = tk.Frame(table_card, bg=SURFACE)
        table_wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        cols = ("no", "session", "zyw", "lokasi", "recorder", "mulai", "durasi", "size", "shift", "health")
        heads = ("#", "SESSION", "DEVICE", "LOCATION", "RECORDER", "START (WIB)", "MIN", "SIZE", "SHIFT", "HEALTH")
        widths = (42, 220, 75, 90, 190, 140, 65, 90, 125, 88)
        self.tree = ttk.Treeview(table_wrap, columns=cols, show="headings", height=12, selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, minwidth=45, anchor="w", stretch=(c in ("session", "recorder")))
        self.tree.tag_configure("CORRUPT", foreground=RED, background="#FFF1F0")
        self.tree.tag_configure("WARN", foreground=AMBER, background="#FFFAED")
        self.tree.tag_configure("OK", foreground=GREEN)
        sb = ttk.Scrollbar(table_wrap, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_wrap, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sb.set, xscrollcommand=hsb.set)
        table_wrap.grid_rowconfigure(0, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_select)

        self.jobs_panel = jobs.JobsPanel(
            self.content, self.jobs,
            dict(surface=SURFACE, ink=INK, muted=MUTED, line=LINE, green=GREEN, amber=AMBER, red=RED),
            self._button)

        bottom = tk.Frame(self.content, bg=BG)
        bottom.pack(fill="x", padx=28, pady=(0, 26))
        detail_card = self._card(bottom)
        detail_card.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(detail_card, text="SESSION INSPECTOR", bg=SURFACE, fg=INK,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=15, pady=(12, 7))
        self.detail = tk.Text(detail_card, height=7, wrap="word", relief="flat", bd=0,
                              bg=SURFACE, fg="#4F5661", font=("Consolas", 9),
                              padx=15, pady=5, state="disabled")
        self.detail.pack(fill="both", expand=True, padx=0, pady=(0, 10))
        action_card = self._card(bottom)
        action_card.pack(side="left", fill="y", padx=(6, 0))
        tk.Label(action_card, text="QUICK ACTIONS", bg=SURFACE, fg=INK,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=15, pady=(12, 8))
        actions = tk.Frame(action_card, bg=SURFACE)
        actions.pack(fill="both", padx=12, pady=(0, 12))
        self._button(actions, "Export to Excel", self.export, dark=True).pack(fill="x", pady=3)
        self._button(actions, "Preview folder plan", self.preview_org, dark=False).pack(fill="x", pady=3)
        self._button(actions, "Arrange folders", self.apply_org, dark=False).pack(fill="x", pady=3)
        self._button(actions, "Folder statistics", self.stats_folder, dark=False).pack(fill="x", pady=3)
        self._button(actions, "Preview frames", self.preview_frames, dark=False).pack(fill="x", pady=3)
        self._button(actions, "Hand check", self.hand_check_run, dark=False).pack(fill="x", pady=3)

    def _button(self, parent, text, command, dark=False):
        bg, fg = (DARK, "white") if dark else ("#F2F3F5", INK)
        hover = ("#30343B",) if dark else ("#E7E9ED",)
        b = tk.Button(parent, text=text, command=command, relief="flat", bd=0,
                      bg=bg, fg=fg, activebackground=hover[0], activeforeground=fg,
                      font=("Segoe UI", 8, "bold"), padx=13, pady=9, cursor="hand2")
        return b

    def _filter_field(self, parent, label, var, width):
        wrap = tk.Frame(parent, bg=SURFACE)
        wrap.pack(side="left", padx=(0, 7), anchor="s")
        tk.Label(wrap, text=label, bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", pady=(0, 4))
        entry = ttk.Entry(wrap, textvariable=var, width=width)
        entry.pack(ipady=3)
        return entry

    def status(self, msg, state="working"):
        self.status_pill.config(text="鈼? " + msg.upper(),
                                bg="#FFF3D9" if state == "working" else ("#FCE9E8" if state == "error" else "#E7F3E9"),
                                fg=AMBER if state == "working" else (RED if state == "error" else GREEN))

    def browse(self):
        p = filedialog.askdirectory(initialdir=self.path_var.get() or "I:\\")
        if p:
            self.path_var.set(p)

    def scan(self):
        path = self.path_var.get().strip()
        if not os.path.isdir(path):
            messagebox.showerror("ZYWtool", f"Folder tidak ditemukan:\n{path}")
            return
        msg = self.jobs.conflict("scan", path)
        if msg:
            messagebox.showwarning("ZYWtool", msg)
            return
        full = self.mode_var.get() == "full"
        hand = self.hand_var.get()
        self._scan_btn_text = self.scan_btn.cget("text")
        self.scan_btn.config(state="disabled", text="SCANNING...")
        self.status("Scan in progress")

        def work(job):
            def prog(i, n, name):
                job.progress = f"{i}/{n}"
                job.message = name
            core.LAST_HAND_REPORT = None
            sess = core.scan_all(path, full=full, hand_check=hand, hand_cfg=self.cfg.get("hand_check"),
                                 progress=prog, should_stop=job.cancel.is_set)
            if job.cancel.is_set():
                return None
            for s in sess:
                core.split_shifts(s, self.cfg["shifts"])
            if hand and core.LAST_HAND_REPORT:
                job.output = core.LAST_HAND_REPORT
            return sess

        def done(job, result, err):
            if job.state == "stopped":
                self.scan_btn.config(state="normal", text=self._scan_btn_text)
                self.status("Scan stopped", "ready")
                return
            self.scan_done(result or [], err)

        try:
            self.jobs.start_thread("scan", "Scan + Hand check" if hand else "Scan", path, work, done)
        except jobs.JobConflict as e:
            self.scan_btn.config(state="normal", text=self._scan_btn_text)
            messagebox.showwarning("ZYWtool", str(e))

    def scan_done(self, sess, err):
        self.scan_btn.config(state="normal", text="RUN SCAN  鈫?)
        if err:
            self.status("Scan failed", "error")
            messagebox.showerror("ZYWtool", f"Scan gagal:\n{err}")
            return
        self.sessions = sess
        self.by_name = {s.name: s for s in sess}
        labels = ["(semua)"] + [x[2] for x in self.cfg["shifts"]] + ["DI LUAR SHIFT"]
        self.shift_box["values"] = labels
        self.status("Scan complete", "ready")
        self.refresh()

    def reset_filters(self):
        for v in (self.sess_from, self.sess_to, self.time_from, self.time_to):
            v.set("")
        self.shift_var.set("(semua)")
        self.refresh()

    def refresh(self):
        def num(v):
            v = v.get().strip()
            return int(v) if v.isdigit() else None
        def txt(v):
            return v.get().strip() or None
        try:
            self.view = core.apply_filter(self.sessions, sess_from=num(self.sess_from),
                sess_to=num(self.sess_to), time_from=txt(self.time_from), time_to=txt(self.time_to),
                shift=self.shift_var.get())
        except ValueError:
            messagebox.showerror("ZYWtool", "Format jam harus HH:MM, contoh 11:00")
            return
        self.tree.delete(*self.tree.get_children())
        for s in self.view:
            self.tree.insert("", "end", iid=s.name, tags=(s.health,), values=(
                s.number, s.name, s.device_no, s.location, s.capturer,
                s.start.strftime("%Y-%m-%d %H:%M") if s.start else "-",
                f"{s.duration_s / 60:.1f}", f"{s.size / 1e6:,.0f} MB", s.shift, s.health))
        self.table_count.set(f"{len(self.view):,} RECORDS")
        self.filter_count.set(f"Showing {len(self.view):,} of {len(self.sessions):,} sessions")
        self.update_summary()

    def update_summary(self):
        v = self.view
        size = sum(s.size for s in v) / 1e9
        dur = sum(s.duration_s for s in v)
        q = [s for s in v if s.health != "CORRUPT"]
        self.metric_vars["sessions"].set(f"{len(v):,}")
        self.metric_vars["qualified"].set(f"{len(q):,}")
        self.metric_vars["storage"].set(f"{size:,.2f} GB")
        self.metric_vars["duration"].set(fmt_hms(dur))

    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        s = self.by_name.get(sel[0])
        if not s:
            return
        lines = [f"{s.name}  |  {s.task}",
            f"Recorder: {s.capturer}   Device: {s.device_id}   Location: {s.location}",
            f"Start: {s.start:%Y-%m-%d %H:%M:%S} WIB   End: {s.end:%H:%M:%S}   Duration: {fmt_hms(s.duration_s)}" if s.start and s.end else f"Duration: {fmt_hms(s.duration_s)}",
            f"Health: {s.health}   Stop cause: {s.stop_cause or '-'}   Shift: {s.shift}",
            f"Overtime: {s.overtime_min:.1f} minutes",
            "Shift breakdown: " + (", ".join(f"{k}={v:.1f} min" for k, v in s.split.items()) or "-"),
            "Files: " + str(len(s.files))]
        if getattr(s, "hand", None):
            lines.append(handcheck.summary_line(s.hand))
        lines += [f"ERROR: {e}" for e in s.errors]
        lines += [f"WARN: {w}" for w in s.warnings]
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", "\n".join(lines))
        self.detail.config(state="disabled")

    def export(self):
        if not self.view:
            messagebox.showinfo("ZYWtool", "Belum ada sesi. Scan dulu.")
            return
        try:
            path, n = core.export_excel(self.view, self.cfg)
        except Exception as e:
            messagebox.showerror("ZYWtool", f"Export gagal:\n{e}")
            return
        self.status("Excel exported", "ready")
        messagebox.showinfo("ZYWtool", f"Export selesai.\n{n} recorder-shift di:\n{path}\nSheet 'Cek File' berisi status tiap sesi.")

    def preview_org(self):
        if not self.view:
            messagebox.showinfo("ZYWtool", "Belum ada sesi. Scan dulu.")
            return
        root = self.path_var.get().strip()
        plan = core.arrange(self.view, self.cfg, root, apply=False)
        groups = sorted({os.path.basename(os.path.dirname(d)) for _, d in plan})
        sample = "\n".join(groups[:8])
        messagebox.showinfo("Preview folder plan", f"{len(plan)} sesi akan dipindah ke {len(groups)} folder grup di:\n{root}\n\nContoh folder grup:\n{sample}")

    def apply_org(self):
        if not self.view:
            messagebox.showinfo("ZYWtool", "Belum ada sesi. Scan dulu.")
            return
        root = self.path_var.get().strip()
        block = self.jobs.guard_arrange(root)
        if block:
            messagebox.showwarning("ZYWtool", block)
            return
        if not messagebox.askyesno("Konfirmasi pemindahan", "Pindahkan sesi ke folder grup di dalam:\n" + root + "\n\nNama folder session tidak berubah. Pemindahan dicatat di folder logs untuk undo."):
            return
        self.status("Arranging folders")
        self.root.update_idletasks()
        try:
            plan = core.arrange(self.view, self.cfg, root, apply=True)
        except Exception as e:
            self.status("Arrange failed", "error")
            messagebox.showerror("ZYWtool", str(e))
            return
        self.status("Folder arrangement complete", "ready")
        self.refresh()
        messagebox.showinfo("ZYWtool", f"Selesai. {len(plan)} sesi diproses.")

    def stats_folder(self):
        folder = filedialog.askdirectory(initialdir="I:/")
        if not folder:
            return
        self.status("Calculating folder statistics")
        self.root.update_idletasks()
        try:
            total, groups = core.folder_stats(folder)
            saved = core.save_folder_summary(folder, total, groups)
        except Exception as e:
            self.status("Folder stats failed", "error")
            messagebox.showerror("ZYWtool", str(e))
            return
        self.status("Folder statistics ready", "ready")
        heads = ["Group", "Sessions", "Size (GB)", "Duration", "OK", "WARN", "CORRUPT"]
        rows = [[name, str(r["sesi"]), core._gb(r["size"]), core.fmt_hms(r["durasi_s"]),
                 str(r["ok"]), str(r["warn"]), str(r["corrupt"])] for name, r in groups.items()]
        rows.append(["TOTAL", str(total["sesi"]), core._gb(total["size"]), core.fmt_hms(total["durasi_s"]),
                     str(total["ok"]), str(total["warn"]), str(total["corrupt"])])
        gw = min(72, max(len(r[0]) for r in rows) + 2)
        widths = [max(gw, 12), 10, 11, 11, 6, 6, 9]

        win = tk.Toplevel(self.root)
        win.title("Folder statistics")
        win.geometry("1180x620")
        win.configure(bg=BG)
        tk.Label(win, text="FOLDER STATISTICS", bg=BG, fg=INK,
                 font=("Segoe UI Semibold", 17)).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(win, text=folder, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(0, 6))
        tk.Label(win, text="Klik satu nilai untuk memilihnya lalu Ctrl+C. Klik kanan: copy nilai / baris / seluruh tabel.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(0, 8))

        outer = tk.Frame(win, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
        outer.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        canvas = tk.Canvas(outer, bg=SURFACE, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        hsb = ttk.Scrollbar(win, orient="horizontal", command=canvas.xview)
        inner = tk.Frame(canvas, bg=SURFACE)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        hsb.pack(fill="x", padx=18)
        win.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        state = {"cell": None, "row": 0}
        table_text = "\n".join(["\t".join(heads)] + ["\t".join(r) for r in rows])

        def to_clip(text, msg):
            win.clipboard_clear()
            win.clipboard_append(text)
            self.status(msg, "ready")

        menu = tk.Menu(win, tearoff=0)
        menu.add_command(label="Copy value",
                         command=lambda: to_clip(state["cell"].get() if state["cell"] else "", "Value copied"))
        menu.add_command(label="Copy row",
                         command=lambda: to_clip("\t".join(rows[state["row"]]), "Row copied"))
        menu.add_command(label="Copy whole table", command=lambda: to_clip(table_text, "Table copied"))

        def select_all(ev):
            ev.widget.focus_set()
            ev.widget.select_range(0, "end")

        def popup(ev, ri):
            state["cell"], state["row"] = ev.widget, ri
            ev.widget.select_range(0, "end")
            menu.tk_popup(ev.x_root, ev.y_root)

        for c, (h, w) in enumerate(zip(heads, widths)):
            tk.Label(inner, text=h.upper(), bg=SURFACE, fg=MUTED, font=("Segoe UI", 8, "bold"),
                     anchor="w", width=w).grid(row=0, column=c, padx=2, pady=(8, 4), sticky="w")
        for ri, row in enumerate(rows):
            is_total = row[0] == "TOTAL"
            for c, val in enumerate(row):
                cell = tk.Entry(inner, width=widths[c], relief="flat", bd=0, highlightthickness=1,
                                highlightbackground=LINE, highlightcolor=LINE, fg=INK, justify="left",
                                font=("Segoe UI Semibold" if is_total else "Segoe UI", 10),
                                readonlybackground="#E9F4DB" if is_total else SURFACE)
                cell.insert(0, val)
                cell.configure(state="readonly")
                cell.bind("<ButtonRelease-1>", select_all)
                cell.bind("<Button-3>", lambda ev, ri=ri: popup(ev, ri))
                cell.grid(row=ri + 1, column=c, padx=2, pady=2, sticky="w")
        tk.Label(win, text=f"Report saved: {saved}", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=18, pady=(4, 12))

    def _resolve_target(self, s, fallback):
        """Path target untuk proses latar belakang: sesi terpilih (dicari ulang kalau sudah dipindah
        oleh arrange) atau folder Data Source."""
        if s is not None:
            p = core.resolve_session_path(s, self.path_var.get().strip())
            if p:
                return p
            messagebox.showerror("ZYWtool", f"Folder sesi {s.name} tidak ditemukan.\n"
                                            "Kemungkinan dipindah atau dihapus. Scan ulang dulu.")
            return None
        if not os.path.isdir(fallback):
            messagebox.showerror("ZYWtool", f"Folder tidak ditemukan:\n{fallback}")
            return None
        return fallback

    def _selected_session(self):
        sel = self.tree.selection()
        return self.by_name.get(sel[0]) if sel else None

    def hand_check_run(self):
        """Fitur independen: cek tangan pada sesi yang dipilih di tabel, atau seluruh folder Data Source.
        Hasil: laporan HTML di hand_check/reports (buka lewat panel Background Jobs)."""
        target = self._resolve_target(self._selected_session(), self.path_var.get().strip())
        if not target:
            return
        try:
            self.jobs.start_process("handcheck", "Hand check", target,
                                    ([sys.executable, "--handcheck", target] if getattr(sys, "frozen", False)
                                     else [sys.executable, os.path.join(HERE, "handcheck.py"), target]),
                                    output=os.path.join(HERE, "hand_check", "reports"))
        except jobs.JobConflict as e:
            messagebox.showwarning("Hand check", str(e))
            return
        self.status("Hand check running")

    def preview_frames(self):
        target = self._resolve_target(self._selected_session(), self.path_var.get().strip())
        if not target:
            return
        try:
            self.jobs.start_process("preview", "Preview frames", target,
                                    ([sys.executable, "--preview-frames", target, "--n", "16", "--cam", "0"]
                                     if getattr(sys, "frozen", False) else
                                     [sys.executable, os.path.join(HERE, "preview_frames.py"), target,
                                      "--n", "16", "--cam", "0"]),
                                    output=os.path.join(HERE, "preview"))
        except jobs.JobConflict as e:
            messagebox.showwarning("Preview frames", str(e))
            return
        self.status("Preview frames running")

    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("Preferences")
        win.geometry("720x500")
        win.configure(bg=BG)
        tk.Label(win, text="WORKSPACE PREFERENCES", bg=BG, fg=INK,
                 font=("Segoe UI Semibold", 17)).pack(anchor="w", padx=18, pady=(16, 8))
        card = tk.Frame(win, bg=SURFACE, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        txt = tk.Text(card, wrap="none", relief="flat", font=("Consolas", 10), padx=12, pady=12)
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        keys = ["shifts", "qc", "supervisor", "excel_path", "organized_root", "hand_check"]
        txt.insert("1.0", json.dumps({k: self.cfg[k] for k in keys}, indent=2, ensure_ascii=False))
        def save():
            try:
                new = json.loads(txt.get("1.0", "end"))
                self.cfg.update(new)
                core.save_config(self.cfg)
                messagebox.showinfo("Preferences", "Pengaturan disimpan. Scan ulang agar shift baru diterapkan.", parent=win)
                win.destroy()
            except Exception as e:
                messagebox.showerror("Preferences", f"JSON tidak valid:\n{e}", parent=win)
        self._button(win, "SAVE PREFERENCES", save, dark=True).pack(anchor="e", padx=18, pady=(0, 16))


if __name__ == "__main__":
    if getattr(sys, "frozen", False) and len(sys.argv) > 1:
        # GUI-subprocess mode: the windowed bootloader has no console streams.
        if sys.stdout is None:
            sys.stdout = open(1, "w", encoding="utf-8", closefd=False)
        if sys.stderr is None:
            sys.stderr = open(2, "w", encoding="utf-8", closefd=False)
    if len(sys.argv) >= 3 and sys.argv[1] == "--stats":
        core.print_stats(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "--handcheck":
        import handcheck
        sys.exit(handcheck.main(sys.argv[2:]))
    elif len(sys.argv) >= 3 and sys.argv[1] == "--preview-frames":
        import preview_frames
        sys.exit(preview_frames.main(sys.argv[2:]))
    else:
        root = tk.Tk()
        App(root)
        root.mainloop()

