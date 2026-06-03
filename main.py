import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import sys
import time
import threading
import subprocess
from pathlib import Path

# ── Library import
try:
    from pypdf import PdfReader, PdfWriter  # type: ignore
    PDF_LIB = "pypdf"
except ImportError:
    try:
        from PyPDF2 import PdfReader, PdfWriter   # type: ignore
        PDF_LIB = "PyPDF2"
    except ImportError:
        # Show error before Tk is fully up
        import tkinter.messagebox as _mb
        _root = tk.Tk()
        _root.withdraw()
        _mb.showerror(
            "Missing Library",
            "pypdf is not installed.\n\n"
            "Open a terminal and run:\n\n"
            "    pip install pypdf\n\n"
            "then restart the program."
        )
        sys.exit(1)


#  Colour Palettes

DARK = {
    "bg":       "#0F1117",
    "surface":  "#1A1D27",
    "card":     "#252836",
    "accent":   "#6C63FF",
    "accent2":  "#5A52D5",
    "text":     "#E8E9F3",
    "muted":    "#6B6E8E",
    "success":  "#3ECF8E",
    "error":    "#EF5350",
    "warning":  "#FFB74D",
    "border":   "#2E3145",
    "alt_row":  "#1E2132",
}

LIGHT = {
    "bg":       "#F0F2FF",
    "surface":  "#FFFFFF",
    "card":     "#E4E7FA",
    "accent":   "#5B52E8",
    "accent2":  "#4740C6",
    "text":     "#1A1D27",
    "muted":    "#7A7D9C",
    "success":  "#1E7A4F",
    "error":    "#C62828",
    "warning":  "#BF5B00",
    "border":   "#C9CCE8",
    "alt_row":  "#EEF0FF",
}


#  Core PDF Functions  (self-contained — no external pdf_core.py required)

def _pdf_validate(path: str):
    """Return (ok: bool, status: str)."""
    if not os.path.exists(path):
        return False, "File not found"
    if not path.lower().endswith(".pdf"):
        return False, "Not a .pdf file"
    try:
        r = PdfReader(path)
        if r.is_encrypted:
            return True, "encrypted"
        _ = len(r.pages)
        return True, "ok"
    except Exception as exc:
        return False, f"Corrupted ({exc})"


def _pdf_pages(path: str, password: str = None) -> int:
    """Return page count, -1 if encrypted without password, 0 on error."""
    try:
        r = PdfReader(path)
        if r.is_encrypted:
            if password:
                r.decrypt(password)
            else:
                return -1
        return len(r.pages)
    except Exception:
        return 0


def _pdf_merge(paths, output, password=None, progress_cb=None):
    """Merge PDFs. Returns (True, output_path) or (False, error_msg)."""
    writer = PdfWriter()
    total = len(paths)
    for idx, path in enumerate(paths):
        try:
            reader = PdfReader(path)
            if reader.is_encrypted:
                if not password:
                    return (False,
                            f"'{os.path.basename(path)}' is password-protected.\n"
                            "Enter a password in the Password field.")
                if not reader.decrypt(password):
                    return False, f"Wrong password for: {os.path.basename(path)}"
            for page in reader.pages:
                writer.add_page(page)
        except Exception as exc:
            return False, f"Cannot read '{os.path.basename(path)}':\n{exc}"
        if progress_cb:
            progress_cb(int((idx + 1) / total * 100))
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        with open(output, "wb") as fh:
            writer.write(fh)
        return True, output
    except Exception as exc:
        return False, f"Could not save file:\n{exc}"


def _pdf_split(path, out_dir, password=None, progress_cb=None):
    """Split PDF into single pages. Returns (True, [files]) or (False, msg)."""
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            if not password:
                return False, "PDF is password-protected. Enter a password."
            if not reader.decrypt(password):
                return False, "Wrong password."
        total = len(reader.pages)
        stem = Path(path).stem
        files = []
        os.makedirs(out_dir, exist_ok=True)
        for i, page in enumerate(reader.pages):
            w = PdfWriter()
            w.add_page(page)
            out_path = os.path.join(out_dir, f"{stem}_page_{i + 1:03d}.pdf")
            with open(out_path, "wb") as fh:
                w.write(fh)
            files.append(out_path)
            if progress_cb:
                progress_cb(int((i + 1) / total * 100))
        return True, files
    except Exception as exc:
        return False, str(exc)


def _ts_filename(prefix="merged") -> str:
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.pdf"


def _open_file(path: str):
    """Open a file with the OS default application."""
    try:
        if sys.platform == "win32":
            os.startfile(path)          # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.call(["open", path])
        else:
            subprocess.call(["xdg-open", path])
    except Exception:
        pass


#  Application Class

class PDFMergerApp:
    """PDF Merger Pro — full-featured GUI application."""

    # Initialise main window and state   

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PDF Merger Pro")
        self.root.geometry("880x660")
        self.root.minsize(720, 540)

        # Application state
        self.is_dark    = tk.BooleanVar(value=True)
        self.pdf_files  = []                          # list of file dicts
        self.password   = tk.StringVar()
        self.output_var = tk.StringVar(value=_ts_filename())
        self.theme      = DARK                        # active palette dict

        self._build_menu()
        self._build_ui()
        self._apply_theme()                           # colour pass — must be last
        self._set_status("Ready — click  Add PDFs  to get started.", "muted")

        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    # Menu bar 
    def _build_menu(self):
        mb = tk.Menu(self.root)

        fm = tk.Menu(mb, tearoff=0)
        fm.add_command(label="Add PDFs...",  command=self._add_files)
        fm.add_command(label="Clear List",   command=self._clear_list)
        fm.add_separator()
        fm.add_command(label="Exit",         command=self.root.destroy)
        mb.add_cascade(label="File",  menu=fm)

        tm = tk.Menu(mb, tearoff=0)
        tm.add_command(label="Merge PDFs",   command=self._start_merge)
        tm.add_command(label="Split PDF...", command=self._start_split_dialog)
        mb.add_cascade(label="Tools", menu=tm)

        hm = tk.Menu(mb, tearoff=0)
        hm.add_command(label="About",        command=self._show_about)
        mb.add_cascade(label="Help",  menu=hm)

        self.root.config(menu=mb)

    #  Widget construction (NO colours here — all applied in _apply_theme) 

    def _build_ui(self):
        r = self.root

        #  Header 
        self.f_header = tk.Frame(r, height=54)
        self.f_header.pack(fill="x")
        self.f_header.pack_propagate(False)

        self.lbl_title = tk.Label(
            self.f_header,
            text="  PDF Merger Pro",
            font=("Segoe UI", 15, "bold"),
            anchor="w")
        self.lbl_title.pack(side="left", padx=16, pady=10)

        self.lbl_lib = tk.Label(
            self.f_header,
            text=f"using {PDF_LIB}",
            font=("Segoe UI", 8))
        self.lbl_lib.pack(side="right", padx=14)

        # Dark-mode toggle — NOTE: activebackground is set in _apply_theme()
        self.chk_dark = tk.Checkbutton(
            self.f_header,
            text="Dark Mode",
            variable=self.is_dark,
            command=self._toggle_theme,
            font=("Segoe UI", 9),
            relief="flat",
            bd=0,
            cursor="hand2")
        self.chk_dark.pack(side="right", padx=4)

        # Toolbar 
        self.f_toolbar = tk.Frame(r, height=42)
        self.f_toolbar.pack(fill="x")
        self.f_toolbar.pack_propagate(False)

        _btn = dict(font=("Segoe UI", 9), padx=10, pady=5,
                    relief="flat", bd=0, cursor="hand2")

        self.btn_add    = tk.Button(self.f_toolbar, text="+ Add PDFs",
                                    command=self._add_files,       **_btn)
        self.btn_up     = tk.Button(self.f_toolbar, text="^ Up",
                                    command=self._move_up,          **_btn)
        self.btn_down   = tk.Button(self.f_toolbar, text="v Down",
                                    command=self._move_down,        **_btn)
        self.btn_remove = tk.Button(self.f_toolbar, text="x Remove",
                                    command=self._remove_selected,  **_btn)
        self.btn_clear  = tk.Button(self.f_toolbar, text="Clear All",
                                    command=self._clear_list,       **_btn)

        for i, btn in enumerate([self.btn_add, self.btn_up, self.btn_down,
                                  self.btn_remove, self.btn_clear]):
            btn.pack(side="left", padx=(14 if i == 0 else 4, 0), pady=5)

        # Column headers 
        self.f_list_wrap = tk.Frame(r)
        self.f_list_wrap.pack(fill="both", expand=True, padx=12, pady=(6, 0))

        self.f_col_header = tk.Frame(self.f_list_wrap, height=24)
        self.f_col_header.pack(fill="x")
        self.f_col_header.pack_propagate(False)

        self.lbl_col_no   = tk.Label(self.f_col_header, text=" #",
                                     font=("Segoe UI", 8, "bold"),
                                     width=4, anchor="w")
        self.lbl_col_name = tk.Label(self.f_col_header, text="File Name",
                                     font=("Segoe UI", 8, "bold"), anchor="w")
        self.lbl_col_size = tk.Label(self.f_col_header, text="Size",
                                     font=("Segoe UI", 8, "bold"),
                                     width=9, anchor="e")
        self.lbl_col_pg   = tk.Label(self.f_col_header, text="Pages",
                                     font=("Segoe UI", 8, "bold"),
                                     width=9, anchor="e")
        self.lbl_col_st   = tk.Label(self.f_col_header, text="Status",
                                     font=("Segoe UI", 8, "bold"),
                                     width=11, anchor="center")

        self.lbl_col_no.pack(  side="left",  padx=(6, 0))
        self.lbl_col_name.pack(side="left",  padx=(6, 0), fill="x", expand=True)
        self.lbl_col_st.pack(  side="right", padx=6)
        self.lbl_col_pg.pack(  side="right")
        self.lbl_col_size.pack(side="right")

        # File listbox + scrollbar
        self.f_lb = tk.Frame(self.f_list_wrap)
        self.f_lb.pack(fill="both", expand=True)

        self.scrollbar = tk.Scrollbar(self.f_lb, orient="vertical")
        self.scrollbar.pack(side="right", fill="y")

        self.listbox = tk.Listbox(
            self.f_lb,
            yscrollcommand=self.scrollbar.set,
            font=("Consolas", 9),
            selectmode="extended",
            activestyle="none",
            relief="flat",
            bd=0,
            highlightthickness=1)
        self.listbox.pack(fill="both", expand=True)
        self.scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<Double-Button-1>", self._on_double_click)

        # Summary row
        self.summary_var = tk.StringVar(value="  No files added yet.")
        self.lbl_summary = tk.Label(
            self.f_list_wrap,
            textvariable=self.summary_var,
            font=("Segoe UI", 8),
            anchor="w")
        self.lbl_summary.pack(fill="x", pady=(3, 0))

        # Options row
        self.f_opts = tk.Frame(r)
        self.f_opts.pack(fill="x", padx=12, pady=(6, 4))

        self.lbl_out = tk.Label(self.f_opts, text="Output File:",
                                font=("Segoe UI", 9, "bold"))
        self.lbl_out.pack(side="left")

        self.ent_output = tk.Entry(
            self.f_opts,
            textvariable=self.output_var,
            font=("Segoe UI", 9),
            width=34,
            relief="flat",
            bd=1,
            highlightthickness=1)
        self.ent_output.pack(side="left", padx=(6, 2), ipady=3)

        self.btn_browse = tk.Button(
            self.f_opts,
            text="...",
            font=("Segoe UI", 9, "bold"),
            command=self._browse_output,
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=6,
            pady=3)
        self.btn_browse.pack(side="left", padx=(0, 16))

        self.lbl_pw = tk.Label(self.f_opts,
                               text="Password (encrypted PDFs):",
                               font=("Segoe UI", 9, "bold"))
        self.lbl_pw.pack(side="left")

        self.ent_pw = tk.Entry(
            self.f_opts,
            textvariable=self.password,
            font=("Segoe UI", 9),
            width=14,
            show="*",
            relief="flat",
            bd=1,
            highlightthickness=1)
        self.ent_pw.pack(side="left", padx=(6, 0), ipady=3)

        # Progress bar
        self.f_prog = tk.Frame(r)
        self.f_prog.pack(fill="x", padx=12, pady=(6, 2))

        self.progress = ttk.Progressbar(
            self.f_prog,
            orient="horizontal",
            mode="determinate",
            length=200)
        self.progress.pack(fill="x")

        # Action buttons
        self.f_actions = tk.Frame(r)
        self.f_actions.pack(fill="x", padx=12, pady=(6, 8))

        _big = dict(font=("Segoe UI", 11, "bold"),
                    padx=22, pady=8, relief="flat", bd=0, cursor="hand2")

        self.btn_merge = tk.Button(self.f_actions, text="Merge PDFs",
                                   command=self._start_merge, **_big)
        self.btn_merge.pack(side="left", padx=(0, 10))

        self.btn_split = tk.Button(self.f_actions, text="Split PDF",
                                   command=self._start_split_dialog, **_big)
        self.btn_split.pack(side="left")

        # Status bar
        self.f_status = tk.Frame(r, height=26)
        self.f_status.pack(fill="x", side="bottom")
        self.f_status.pack_propagate(False)

        self.status_var = tk.StringVar(value="")
        self.lbl_status = tk.Label(
            self.f_status,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            anchor="w")
        self.lbl_status.pack(fill="both", padx=12, pady=3)

    # Theme

    def _toggle_theme(self):
        self.theme = DARK if self.is_dark.get() else LIGHT
        self._apply_theme()

    def _apply_theme(self):
        """Apply the active colour palette to every widget."""
        t   = self.theme
        bg  = t["bg"]
        sur = t["surface"]
        crd = t["card"]
        acc = t["accent"]
        ac2 = t["accent2"]
        txt = t["text"]
        mut = t["muted"]
        brd = t["border"]

        self.root.configure(bg=bg)

        # Header
        self.f_header.configure(bg=sur)
        self.lbl_title.configure(bg=sur, fg=acc)
        self.lbl_lib.configure(  bg=sur, fg=mut)

        # Checkbutton: activebackground MUST be a real colour (not "")
        self.chk_dark.configure(
            bg=sur, fg=mut,
            activebackground=sur,   # ← was "" in original — fixed
            activeforeground=txt,
            selectcolor=sur)

        # Toolbar
        self.f_toolbar.configure(bg=crd)
        for btn in (self.btn_add, self.btn_up, self.btn_down,
                    self.btn_remove, self.btn_clear):
            btn.configure(bg=crd, fg=txt,
                          activebackground=acc,
                          activeforeground="white")

        # List area
        self.f_list_wrap.configure(bg=bg)
        self.f_col_header.configure(bg=crd)
        for lbl in (self.lbl_col_no, self.lbl_col_name,
                    self.lbl_col_size, self.lbl_col_pg, self.lbl_col_st):
            lbl.configure(bg=crd, fg=mut)

        self.f_lb.configure(bg=bg)
        self.listbox.configure(
            bg=sur, fg=txt,
            selectbackground=acc,
            selectforeground="white",
            highlightbackground=brd,
            highlightcolor=acc)
        self.scrollbar.configure(bg=crd, troughcolor=sur)
        self.lbl_summary.configure(bg=bg, fg=mut)

        # Options
        self.f_opts.configure(bg=bg)
        self.lbl_out.configure(bg=bg, fg=txt)
        self.lbl_pw.configure( bg=bg, fg=txt)
        self.ent_output.configure(
            bg=sur, fg=txt, insertbackground=txt,
            highlightbackground=brd, highlightcolor=acc)
        self.ent_pw.configure(
            bg=sur, fg=txt, insertbackground=txt,
            highlightbackground=brd, highlightcolor=acc)
        self.btn_browse.configure(
            bg=crd, fg=txt,
            activebackground=acc, activeforeground="white")

        # Progress bar via ttk style
        self.f_prog.configure(bg=bg)
        sty = ttk.Style()
        sty.theme_use("clam")
        sty.configure("TProgressbar",
                       troughcolor=crd,
                       background=acc,
                       darkcolor=acc,
                       lightcolor=acc,
                       bordercolor=brd)

        # Action buttons
        self.f_actions.configure(bg=bg)
        self.btn_merge.configure(
            bg=acc, fg="white",
            activebackground=ac2, activeforeground="white")
        self.btn_split.configure(
            bg=crd, fg=txt,
            activebackground=acc, activeforeground="white")

        # Status bar
        self.f_status.configure(bg=sur)
        self.lbl_status.configure(bg=sur)

        # Refresh rows with new row colours
        self._refresh_list()

    # File management 

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select PDF Files",
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")])
        added = skipped = 0
        for path in map(str, paths):
            if any(f["path"] == path for f in self.pdf_files):
                skipped += 1
                continue
            ok, status = _pdf_validate(path)
            pages   = _pdf_pages(path) if ok else 0
            size_kb = round(os.path.getsize(path) / 1024, 1)
            self.pdf_files.append(
                {"path": path, "pages": pages,
                 "status": status, "size_kb": size_kb})
            added += 1

        if added:
            self._refresh_list()
            msg = f"Added {added} file(s)"
            if skipped:
                msg += f"  ({skipped} duplicate(s) skipped)"
            self._set_status(f"{msg}.  Total: {len(self.pdf_files)}", "success")
        elif skipped:
            self._set_status("All selected files are already in the list.", "muted")

    def _remove_selected(self):
        sel = list(self.listbox.curselection())
        if not sel:
            self._set_status("Select at least one file to remove.", "warning")
            return
        for i in reversed(sel):
            del self.pdf_files[i]
        self._refresh_list()
        self._set_status(f"Removed {len(sel)} file(s).", "muted")

    def _clear_list(self):
        if not self.pdf_files:
            return
        if not messagebox.askyesno("Clear List",
                                   "Remove all files from the list?"):
            return
        self.pdf_files.clear()
        self._refresh_list()
        self._set_status("List cleared.", "muted")

    def _move_up(self):
        sel = list(self.listbox.curselection())
        if not sel or sel[0] == 0:
            return
        for i in sel:
            self.pdf_files[i - 1], self.pdf_files[i] = \
                self.pdf_files[i], self.pdf_files[i - 1]
        self._refresh_list()
        for i in sel:
            self.listbox.selection_set(i - 1)

    def _move_down(self):
        sel = list(self.listbox.curselection())
        if not sel or sel[-1] >= len(self.pdf_files) - 1:
            return
        for i in reversed(sel):
            self.pdf_files[i], self.pdf_files[i + 1] = \
                self.pdf_files[i + 1], self.pdf_files[i]
        self._refresh_list()
        for i in sel:
            self.listbox.selection_set(i + 1)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save Merged PDF As",
            defaultextension=".pdf",
            filetypes=[("PDF Files", "*.pdf")],
            initialfile=self.output_var.get())
        if path:
            self.output_var.set(path)

    def _on_double_click(self, _event=None):
        sel = self.listbox.curselection()
        if sel:
            _open_file(self.pdf_files[sel[0]]["path"])

    # Merge

    def _start_merge(self):
        if not self.pdf_files:
            messagebox.showwarning("No Files",
                "Add at least 2 PDF files before merging.")
            return
        if len(self.pdf_files) < 2:
            messagebox.showwarning("Too Few Files",
                "You need at least 2 PDF files to merge.")
            return

        output = self.output_var.get().strip()
        if not output:
            output = _ts_filename()
            self.output_var.set(output)
        if not output.lower().endswith(".pdf"):
            output += ".pdf"

        # Ask for save location if only a bare filename (no directory) was given
        if not os.path.isabs(output):
            save_path = filedialog.asksaveasfilename(
                title="Save Merged PDF",
                defaultextension=".pdf",
                filetypes=[("PDF Files", "*.pdf")],
                initialfile=output)
            if not save_path:
                return
            output = save_path
            self.output_var.set(output)

        self._set_ui_busy(True)
        self.progress["value"] = 0
        self._set_status("Merging PDFs, please wait...", "muted")

        paths    = [f["path"] for f in self.pdf_files]
        password = self.password.get() or None

        def _worker():
            ok, result = _pdf_merge(
                paths, output, password=password,
                progress_cb=lambda v: self.root.after(
                    0, self.progress.configure, {"value": v}))
            self.root.after(0, self._on_merge_done, ok, result, output)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_merge_done(self, ok: bool, result: str, output: str):
        self._set_ui_busy(False)
        if ok:
            self.progress["value"] = 100
            size_kb = round(os.path.getsize(result) / 1024, 1)
            self._set_status(
                f"Merged successfully  ->  {os.path.basename(result)}"
                f"  ({size_kb} KB)", "success")
            if messagebox.askyesno(
                    "Merge Complete!",
                    f"Saved: {result}\n({size_kb} KB)\n\n"
                    "Open the merged PDF now?"):
                _open_file(result)
            self.output_var.set(_ts_filename())   # reset for next merge
        else:
            self.progress["value"] = 0
            self._set_status(f"Merge failed: {result}", "error")
            messagebox.showerror("Merge Failed", result)

    # Split

    def _start_split_dialog(self):
        path = filedialog.askopenfilename(
            title="Select PDF to Split",
            filetypes=[("PDF Files", "*.pdf")])
        if not path:
            return
        out_dir = filedialog.askdirectory(
            title="Choose Output Folder for Split Pages")
        if not out_dir:
            return

        self._set_ui_busy(True)
        self.progress["value"] = 0
        self._set_status(
            f"Splitting  {os.path.basename(path)} ...", "muted")

        password = self.password.get() or None

        def _worker():
            ok, result = _pdf_split(
                path, out_dir, password=password,
                progress_cb=lambda v: self.root.after(
                    0, self.progress.configure, {"value": v}))
            self.root.after(0, self._on_split_done, ok, result, out_dir)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_split_done(self, ok: bool, result, out_dir: str):
        self._set_ui_busy(False)
        if ok:
            self.progress["value"] = 100
            n = len(result)
            self._set_status(
                f"Split into {n} page file(s)  ->  {out_dir}", "success")
            messagebox.showinfo(
                "Split Complete",
                f"Created {n} page file(s) in:\n{out_dir}")
        else:
            self.progress["value"] = 0
            self._set_status(f"Split failed: {result}", "error")
            messagebox.showerror("Split Failed", str(result))

    # UI helpers

    def _refresh_list(self):
        """Redraw the listbox from self.pdf_files."""
        self.listbox.delete(0, tk.END)
        t = self.theme
        total_pages = 0

        for i, f in enumerate(self.pdf_files):
            name    = os.path.basename(f["path"])
            pages   = f["pages"]
            status  = f["status"]
            size_kb = f.get("size_kb", 0)

            if pages == -1:
                pg_str = "  [enc]"
            elif pages == 0:
                pg_str = "  [err]"
            else:
                pg_str = f"{pages:>5} pg"
                total_pages += pages

            sz_str   = f"{size_kb:>6.0f} KB"
            icon     = "[*]" if status == "encrypted" else "[!]" if status not in ("ok","encrypted") else "   "
            line     = f" {i+1:>2}.  {icon}  {name:<44}  {sz_str}  {pg_str}"
            self.listbox.insert(tk.END, line)

            row_bg = t["surface"] if i % 2 == 0 else t["alt_row"]
            if status not in ("ok", "encrypted"):
                fg = t["error"]
            elif status == "encrypted":
                fg = t["warning"]
            else:
                fg = t["text"]
            self.listbox.itemconfig(i, bg=row_bg, fg=fg)

        n = len(self.pdf_files)
        if n == 0:
            self.summary_var.set("  No files added — click  + Add PDFs  to begin.")
        else:
            self.summary_var.set(
                f"  {n} file{'s' if n != 1 else ''}  |  "
                f"{total_pages} total page{'s' if total_pages != 1 else ''}")

    def _set_status(self, msg: str, level: str = "muted"):
        colour_map = {
            "success": self.theme["success"],
            "error":   self.theme["error"],
            "warning": self.theme["warning"],
            "muted":   self.theme["muted"],
        }
        self.status_var.set(f"  {msg}")
        self.lbl_status.configure(fg=colour_map.get(level, self.theme["muted"]))

    def _set_ui_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        for w in (self.btn_add, self.btn_up,    self.btn_down,
                  self.btn_remove, self.btn_clear,
                  self.btn_merge,  self.btn_split,
                  self.ent_output, self.btn_browse, self.ent_pw):
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _show_about(self):
        messagebox.showinfo(
            "About PDF Merger Pro",
            f"PDF Merger Pro  v1.1\n"
            f"Built with Python + {PDF_LIB}\n\n"
            f"Features\n"
            f"------------------------------------\n"
            f"  Merge unlimited PDFs\n"
            f"  Reorder files with Up / Down\n"
            f"  Remove or clear files\n"
            f"  Split PDF into individual pages\n"
            f"  Password-protected PDF support\n"
            f"  Dark and Light mode\n"
            f"  Timestamped output filenames\n"
            f"  Non-blocking threaded operations\n"
            f"  Auto-open merged PDF\n\n"
            f"Tip: Double-click any row to open that PDF."
        )


#  Entry point

def main():
    root = tk.Tk()
    PDFMergerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()