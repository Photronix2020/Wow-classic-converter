"""Small window for people who'd rather not use the command line."""

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, apidb
from .converter import NoAddonFound, convert_path

TARGET_LABELS = {
    "vanilla": "Classic Era / Hardcore / SoD / Anniversary",
    "tbc": "Burning Crusade Classic",
    "mists": "Mists of Pandaria Classic",
}


def open_path(path):
    path = str(path)
    if sys.platform == "win32":
        if path.lower().endswith(".md"):
            # .md usually has no default app on Windows.
            subprocess.Popen(["notepad.exe", path])
        else:
            os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class App:
    def __init__(self, root):
        self.root = root
        self.output = None
        self.report = None
        root.title(f"WoW Classic Addon Converter {__version__}")
        root.minsize(560, 420)

        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)

        ttk.Label(frm, text="Retail or WoW Forever addon (a .zip as downloaded, or the addon folder):").grid(
            row=0, column=0, columnspan=3, sticky="w")
        self.input_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.input_var).grid(row=1, column=0, sticky="ew", pady=4)
        ttk.Button(frm, text="Choose zip…", command=self.pick_zip).grid(row=1, column=1, padx=(6, 0))
        ttk.Button(frm, text="Choose folder…", command=self.pick_folder).grid(row=1, column=2, padx=(6, 0))

        box = ttk.LabelFrame(frm, text="Make it work on", padding=8)
        box.grid(row=2, column=0, columnspan=3, sticky="ew", pady=8)
        self.target_vars = {}
        for t in apidb.TARGETS:
            var = tk.BooleanVar(value=True)
            ttk.Checkbutton(box, text=TARGET_LABELS.get(t, t), variable=var).pack(anchor="w")
            self.target_vars[t] = var

        self.convert_btn = ttk.Button(frm, text="Convert", command=self.convert)
        self.convert_btn.grid(row=3, column=0, columnspan=3, sticky="ew")

        self.log = tk.Text(frm, height=10, wrap="word", state="disabled")
        self.log.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=8)
        frm.rowconfigure(4, weight=1)

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=3, sticky="e")
        self.open_out_btn = ttk.Button(btns, text="Show result", state="disabled",
                                       command=lambda: open_path(self.output.parent))
        self.open_out_btn.pack(side="left")
        self.open_report_btn = ttk.Button(btns, text="Open report", state="disabled",
                                          command=lambda: open_path(self.report))
        self.open_report_btn.pack(side="left", padx=(6, 0))

        self.write("Pick an addon, then press Convert. The result is saved next to it as "
                   "<name>-classic.zip, ready to unzip into your Classic Interface\\AddOns folder.")

    def write(self, text, clear=False):
        self.log.configure(state="normal")
        if clear:
            self.log.delete("1.0", "end")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def pick_zip(self):
        path = filedialog.askopenfilename(filetypes=[("Zip files", "*.zip"), ("All files", "*.*")])
        if path:
            self.input_var.set(path)

    def pick_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.input_var.set(path)

    def convert(self):
        src = Path(self.input_var.get().strip().strip('"'))
        targets = [t for t, v in self.target_vars.items() if v.get()]
        if not src.exists():
            messagebox.showerror("Converter", "Choose an addon zip or folder first.")
            return
        if not targets:
            messagebox.showerror("Converter", "Tick at least one Classic version.")
            return
        stem = src.stem if src.suffix.lower() == ".zip" else src.name
        out = src.with_name(stem + "-classic.zip")
        interfaces = {t: apidb.TARGETS[t][1] for t in targets}

        self.convert_btn.configure(state="disabled")
        self.open_out_btn.configure(state="disabled")
        self.open_report_btn.configure(state="disabled")
        self.write(f"Converting {src.name}…", clear=True)

        def work():
            try:
                results, report = convert_path(src, out, targets, interfaces)
            except NoAddonFound as e:
                self.root.after(0, self.finish, None, None, str(e))
            except Exception as e:  # show anything unexpected instead of dying silently
                self.root.after(0, self.finish, None, None, f"Something went wrong: {e!r}")
            else:
                self.root.after(0, self.finish, (out, report), results, None)

        threading.Thread(target=work, daemon=True).start()

    def finish(self, paths, results, error):
        self.convert_btn.configure(state="normal")
        if error:
            self.write(error)
            return
        self.output, self.report = paths
        for r in results:
            self.write(f"• {r.name}: {r.files_rewritten} files updated, "
                       f"{len(r.findings)} things to check by hand")
            for note in r.notes:
                self.write(f"    {note}")
        self.write(f"\nSaved: {self.output}\nReport: {self.report}")
        self.write("\nIf the game lists it as out of date, tick \"Load out of date AddOns\" "
                   "in the AddOns menu.")
        self.open_out_btn.configure(state="normal")
        self.open_report_btn.configure(state="normal")


def run():
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
