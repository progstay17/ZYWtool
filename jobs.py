"""jobs - manajer proses latar belakang ZYWtool: indikator status, tombol stop, pencegah proses dobel.
ZYWtool contributors

Aturan anti-dobel:
  - scan: hanya satu scan berjalan pada satu waktu
  - handcheck / preview: satu proses per folder (folder yang saling tumpang tindih dianggap sama)
  - arrange (pindah folder) diblokir selama ada proses yang membaca folder itu
Setiap proses subprocess punya file log sendiri di logs/jobs (tidak saling menimpa).
"""
import sys
import itertools
import os
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

HERE = (os.environ.get("ZYWTOOL_HOME") or
        (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
         else os.path.dirname(os.path.abspath(__file__))))
JOB_LOG_DIR = os.path.join(HERE, "logs", "jobs")
_ids = itertools.count(1)


class JobConflict(Exception):
    """Proses serupa sudah berjalan."""


def _norm(p):
    return os.path.normcase(os.path.normpath(p))


def _overlap(a, b):
    a, b = _norm(a), _norm(b)
    return a == b or a.startswith(b + os.sep) or b.startswith(a + os.sep)


def fmt_elapsed(sec):
    sec = int(sec)
    return f"{sec // 3600}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


class Job:
    def __init__(self, kind, label, target):
        self.id = next(_ids)
        self.kind, self.label, self.target = kind, label, target
        self.state = "running"            # running | done | stopped | failed
        self.started = time.time()
        self.ended = None
        self.proc = None
        self.cancel = threading.Event()
        self.log_path = ""
        self.progress = ""
        self.message = ""
        self.output = ""                  # file/folder hasil yang bisa dibuka
        self.stop_requested = False
        self._log = None

    @property
    def elapsed(self):
        return (self.ended or time.time()) - self.started


class JobManager:
    def __init__(self, root, on_change=None):
        self.root = root
        self.on_change = on_change
        self.listeners = []
        self.jobs = []
        self._q = queue.Queue()      # callback dari thread kerja; dibaca HANYA oleh thread utama
        self._last_notify = 0.0
        self.root.after(250, self._tick)

    # ---------- query ----------
    def running(self):
        return [j for j in self.jobs if j.state == "running"]

    def conflict(self, kind, target):
        for j in self.running():
            if kind == "scan" and j.kind == "scan":
                return f"Scan sudah berjalan (job #{j.id}). Stop atau tunggu sampai selesai."
            if j.kind == kind and _overlap(j.target, target):
                return (f"{j.label} untuk folder ini sudah berjalan (job #{j.id}).\n"
                        "Stop atau tunggu sampai selesai supaya hasil tidak dobel.")
        return None

    def guard_arrange(self, root_dir):
        busy = [j for j in self.running() if _overlap(j.target, root_dir)]
        if busy:
            names = ", ".join(f"#{j.id} {j.label}" for j in busy)
            return (f"Folder tidak bisa dipindah selama proses ini masih berjalan: {names}.\n"
                    "Stop atau tunggu sampai selesai.")
        return None

    # ---------- start ----------
    def start_process(self, kind, label, target, argv, output=""):
        msg = self.conflict(kind, target)
        if msg:
            raise JobConflict(msg)
        job = Job(kind, label, target)
        os.makedirs(JOB_LOG_DIR, exist_ok=True)
        job.log_path = os.path.join(JOB_LOG_DIR, f"{kind}_{time.strftime('%Y%m%d_%H%M%S')}_{job.id}.log")
        job.output = output
        log = open(job.log_path, "w", encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        try:
            job.proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            log.close()
            raise
        job._log = log
        self.jobs.append(job)
        self._changed()
        return job

    def start_thread(self, kind, label, target, func, on_done=None):
        """func(job) dijalankan di thread. Pantau job.cancel.is_set() untuk berhenti dengan rapi."""
        msg = self.conflict(kind, target)
        if msg:
            raise JobConflict(msg)
        job = Job(kind, label, target)
        self.jobs.append(job)

        def runner():
            result, err = None, None
            try:
                result = func(job)
            except Exception as e:
                err = e

            def finish():
                job.ended = time.time()
                job.state = "stopped" if job.cancel.is_set() else ("failed" if err else "done")
                self._changed()
                if on_done:
                    on_done(job, result, err)
            self._q.put(finish)         # jangan sentuh Tk dari thread kerja

        threading.Thread(target=runner, daemon=True).start()
        self._changed()
        return job

    # ---------- stop ----------
    @staticmethod
    def _kill_tree(proc):
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=10)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def stop(self, job):
        if job.state != "running":
            return
        job.stop_requested = True
        job.cancel.set()
        job.message = "menghentikan..."
        if job.proc is not None:
            self._kill_tree(job.proc)
            try:
                job.proc.wait(timeout=3)
            except Exception:
                pass
            self._tick(reschedule=False)
        self._changed()

    def stop_all(self):
        for j in list(self.running()):
            self.stop(j)

    def clear_finished(self):
        self.jobs = [j for j in self.jobs if j.state == "running"]
        self._changed()

    # ---------- internal ----------
    def _read_log(self, j, force=False):
        now = time.time()
        # Saat proses sudah exit, baca ekor log sebelum file handle ditutup.
        # Proses singkat dapat selesai di dalam jeda throttle dan kehilangan path hasil terakhir.
        if not force and now - getattr(j, "_last_read", 0) < 1.0 and j.state == "running":
            return
        j._last_read = now
        try:
            with open(j.log_path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return
        if j.kind == "preview":
            m = re.search(r"^(\d+) sesi", text, re.M)
            if m:
                done = len(re.findall(r"^(?:OK|GAGAL)\b", text, re.M))
                j.progress = f"{done}/{m.group(1)}"
        else:
            ms = re.findall(r"\[(\d+)/(\d+)\]", text)
            if ms:
                j.progress = f"{ms[-1][0]}/{ms[-1][1]}"
        mo = re.search(r"^Hasil laporan\s*:\s*(.+)$", text, re.M)
        if mo:
            j.output = mo.group(1).strip()

    def _tick(self, reschedule=True):
        changed = False
        while True:                      # selesaikan thread kerja yang sudah berakhir (di thread utama)
            try:
                fn = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                pass
        for j in self.running():
            if j.proc is None:
                continue
            rc = j.proc.poll()
            self._read_log(j, force=(rc is not None))
            if rc is not None:
                j.ended = time.time()
                j.state = "stopped" if j.stop_requested else ("done" if rc == 0 else "failed")
                try:
                    j._log.close()
                except Exception:
                    pass
                changed = True
        if changed:
            self._changed()
        elif self.running() and time.time() - self._last_notify >= 1.0:
            self._notify()           # segarkan waktu berjalan sekitar sekali per detik
        if reschedule:
            self.root.after(250, self._tick)

    def _notify(self):
        self._last_notify = time.time()
        for fn in list(self.listeners):
            try:
                fn()
            except Exception:
                pass

    def _changed(self):
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass
        self._notify()


class JobsPanel:
    """Kartu 'BACKGROUND JOBS': daftar proses, status, waktu berjalan, progres, tombol Stop / Open / Clear."""

    def __init__(self, parent, manager, theme, button):
        self.m = manager
        t = theme
        self.card = tk.Frame(parent, bg=t["surface"], highlightbackground=t["line"], highlightthickness=1)
        self.card.pack(fill="x", padx=28, pady=(0, 12))
        head = tk.Frame(self.card, bg=t["surface"])
        head.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(head, text="BACKGROUND JOBS", bg=t["surface"], fg=t["ink"],
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        self.count = tk.StringVar(value="NO ACTIVE JOBS")
        tk.Label(head, textvariable=self.count, bg=t["surface"], fg=t["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="right")
        cols = ("id", "job", "target", "state", "elapsed", "progress")
        heads = ("#", "JOB", "TARGET", "STATE", "ELAPSED", "PROGRESS")
        widths = (50, 150, 380, 110, 90, 160)
        wrap = tk.Frame(self.card, bg=t["surface"])
        wrap.pack(fill="x", padx=12)
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", height=3, selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, minwidth=45, anchor="w", stretch=(c == "target"))
        self.tree.tag_configure("running", foreground=t["amber"])
        self.tree.tag_configure("done", foreground=t["green"])
        self.tree.tag_configure("failed", foreground=t["red"], background="#FFF1F0")
        self.tree.tag_configure("stopped", foreground=t["muted"])
        self.tree.pack(fill="x")
        self.tree.bind("<Double-1>", lambda _e: self.open_result())
        bar = tk.Frame(self.card, bg=t["surface"])
        bar.pack(fill="x", padx=14, pady=(8, 12))
        button(bar, "STOP SELECTED", self.stop_selected, dark=True).pack(side="left")
        button(bar, "Stop all", self.m.stop_all, dark=False).pack(side="left", padx=(6, 0))
        button(bar, "Open result", self.open_result, dark=False).pack(side="left", padx=(6, 0))
        button(bar, "Clear finished", self.m.clear_finished, dark=False).pack(side="left", padx=(6, 0))
        self.m.listeners.append(self.refresh)
        self.refresh()

    @staticmethod
    def _short(path):
        parts = os.path.normpath(path).split(os.sep)
        return os.sep.join(parts[-2:]) if len(parts) > 2 else path

    @staticmethod
    def _state_text(j):
        if j.state == "running":
            return "STOPPING..." if j.stop_requested else "RUNNING"
        return j.state.upper()

    @staticmethod
    def _prog(j):
        if j.progress:
            return j.progress + (f"  {j.message}" if j.message and j.state == "running" else "")
        return "starting..." if j.state == "running" else "-"

    def refresh(self):
        want = {str(j.id): j for j in self.m.jobs}
        for iid in self.tree.get_children():
            if iid not in want:
                self.tree.delete(iid)
        existing = set(self.tree.get_children())
        for iid, j in want.items():
            vals = (f"#{j.id}", j.label, self._short(j.target), self._state_text(j),
                    fmt_elapsed(j.elapsed), self._prog(j))
            if iid in existing:
                self.tree.item(iid, values=vals, tags=(j.state,))
            else:
                self.tree.insert("", "end", iid=iid, values=vals, tags=(j.state,))
        n = len(self.m.running())
        self.count.set(f"{n} RUNNING" if n else ("NO ACTIVE JOBS" if not want else f"{len(want)} FINISHED"))

    def _selected(self):
        sel = self.tree.selection()
        if sel:
            return next((j for j in self.m.jobs if str(j.id) == sel[0]), None)
        running = self.m.running()
        return running[0] if len(running) == 1 else None

    def stop_selected(self):
        j = self._selected()
        if j is None:
            messagebox.showinfo("Background jobs", "Pilih satu proses di daftar dulu.")
        elif j.state != "running":
            messagebox.showinfo("Background jobs", f"Job #{j.id} sudah {j.state}.")
        else:
            self.m.stop(j)

    def open_result(self):
        j = self._selected()
        if j is None:
            finished = [x for x in self.m.jobs if x.output and os.path.exists(x.output)]
            j = finished[-1] if finished else None
        if j is None or not j.output or not os.path.exists(j.output):
            messagebox.showinfo("Background jobs", "Belum ada hasil untuk dibuka.")
            return
        try:
            os.startfile(j.output)
        except Exception as e:
            messagebox.showerror("Background jobs", str(e))

