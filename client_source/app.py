"""
AutoHDR Download (Remake By Mystic) - Version 2.0.0
Professional Pitch-Black UI built with Python Tkinter / ttk.
Anti-crack Client-Server Architecture:
  - Core link resolving logic is protected on the VPS server with v811 fallback.
  - License and Machine HWID are validated on the VPS server.
  - Real-time countdown timer for license expiration.
  - iPhone Dynamic Island / iOS style slide-down welcome banner.
  - Mandatory auto-update system with self-replacement on Windows.
"""
from __future__ import annotations
import os
import sys
import re
import json
import time
import queue
import threading
import subprocess
from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from hwid import get_hwid
from downloader import DownloadJob
from platform_support import IS_MAC, MacButton, config_path, mac_arch, open_folder
from mac_updates import select_release, download_release
from network_support import ssl_context

APP_VERSION = "2.0.1"

# ==============================================================================
# PITCH-BLACK THEME PALETTE (Professional Carbon & Silver)
# ==============================================================================
THEME = {
    "BG": "#050505",
    "CARD": "#0C0C0E",
    "CARD_HEADER": "#101014",
    "INPUT_BG": "#141418",
    "ROW_ALT": "#0F0F13",
    "ROW_SEL": "#22222A",
    "BORDER": "#222228",
    "BORDER_FOCUS": "#FFFFFF",
    "PRIMARY_BG": "#FFFFFF",
    "PRIMARY_FG": "#050505",
    "PRIMARY_HOVER": "#D4D4D8",
    "SEC_BG": "#18181D",
    "SEC_FG": "#F4F4F5",
    "SEC_HOVER": "#27272F",
    "DANGER_BG": "#1F1215",
    "DANGER_FG": "#F87171",
    "DANGER_HOVER": "#36191E",
    "TEXT": "#FFFFFF",
    "TEXT_MUTED": "#8E8E99",
    "SUCCESS": "#10B981",
    "WARNING": "#F59E0B",
    "ERROR": "#EF4444",
    "INFO": "#E4E4E7",

    "FONT_BRAND": ("Bahnschrift", 17, "bold"),
    "FONT_SUBBRAND": ("Helvetica Neue" if IS_MAC else "Segoe UI Semibold", 8),
    "FONT_CARD_TITLE": ("Bahnschrift", 10, "bold"),
    "FONT_LABEL": ("Helvetica Neue" if IS_MAC else "Segoe UI Semibold", 8),
    "FONT_BODY": ("Helvetica Neue" if IS_MAC else "Segoe UI", 9),
    "FONT_BTN": ("Helvetica Neue" if IS_MAC else "Segoe UI Semibold", 9),
    "FONT_CODE": ("Cascadia Mono", 9),
}

BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
CONFIG_FILE = config_path(BASE_DIR)
BUTTON_CLASS = MacButton if IS_MAC else tk.Button

if IS_MAC:
    for _name, _font in list(THEME.items()):
        if _name.startswith("FONT_"):
            THEME[_name] = ("Menlo" if _name == "FONT_CODE" else "Helvetica Neue", *_font[1:])


def is_newer_version(latest_str: str, current_str: str) -> bool:
    """Compares version tuples like 2.0.1 > 2.0.0."""
    def parse_v(s: str) -> List[int]:
        parts = re.findall(r"\d+", str(s))
        return [int(p) for p in parts] if parts else [0]
    return parse_v(latest_str) > parse_v(current_str)


def clean_child_env() -> Dict[str, str]:
    """
    Environment for processes started from this app.
    A PyInstaller onefile exe marks its environment as "already unpacked". If the new exe
    inherits that, it tries to reuse this instance's temp folder, which is deleted on exit,
    and fails to start.
    """
    env = os.environ.copy()
    mei = getattr(sys, "_MEIPASS", "")
    for key in list(env):
        if key.startswith(("_MEI", "_PYI")):
            env.pop(key)
        elif mei and mei.lower() in env[key].lower():
            if key.upper() == "PATH":
                env[key] = os.pathsep.join(p for p in env[key].split(os.pathsep) if mei.lower() not in p.lower())
            else:
                env.pop(key)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def build_update_script(old_pid: int, current_exe: Path, new_exe: Path) -> str:
    """Batch script: wait for old_pid to exit, replace current_exe with new_exe, start it, delete itself."""
    return f'''@echo off
chcp 65001 > nul
set "OLD_PID={old_pid}"
set "OLD_EXE={current_exe}"
set "NEW_EXE={new_exe}"
set /a WAITED=0

:wait_loop
tasklist /fi "pid eq %OLD_PID%" /nh /fo csv 2>nul | find """%OLD_PID%""" > nul
if errorlevel 1 goto replace
set /a WAITED+=1
if %WAITED% geq 30 (
    taskkill /f /pid %OLD_PID% > nul 2>&1
    goto replace
)
timeout /t 1 /nobreak > nul
goto wait_loop

:replace
rem The onefile launcher can keep the exe locked a moment longer, so retry the delete.
set /a TRIES=0
:del_loop
del /f /q "%OLD_EXE%" > nul 2>&1
if not exist "%OLD_EXE%" goto move_new
set /a TRIES+=1
if %TRIES% geq 30 goto start_app
timeout /t 1 /nobreak > nul
goto del_loop

:move_new
move /y "%NEW_EXE%" "%OLD_EXE%" > nul

:start_app
start "" "%OLD_EXE%"
(goto) 2>nul & del /f /q "%~f0"
'''


class PhotoshootApp:
    def __init__(self, startup_checks: bool = True):
        self.root = tk.Tk()
        self.root.title(f"AutoHDR Download v{APP_VERSION}")
        self.root.geometry("1160x780" if IS_MAC else "1160x840")
        self.root.minsize(980, 700)
        self.root.configure(bg=THEME["BG"])

        # Hardware identity
        self.hwid = get_hwid()

        # Runtime state
        self.jobs: List[DownloadJob] = []
        self._job_rows: Dict[str, DownloadJob] = {}
        self._log_queue: queue.Queue = queue.Queue()
        self._ui_queue: queue.Queue = queue.Queue()
        self._progress_queue: queue.Queue = queue.Queue()
        self._semaphore = threading.Semaphore(3)

        # Config & Vars
        self._cfg = self._load_config()
        self.server_var = tk.StringVar(value=self._cfg.get("server_url", "http://103.74.103.68:8080"))
        self.license_var = tk.StringVar(value=self._cfg.get("license_key", ""))
        self.save_dir_var = tk.StringVar(value=self._cfg.get("save_dir", str(Path.home() / "Downloads" / "AutoHDR")))
        self.threads_var = tk.StringVar(value=str(self._cfg.get("threads", 6)))
        self.max_ps_var = tk.StringVar(value=str(self._cfg.get("max_ps", 3)))
        self.url_var = tk.StringVar()
        self.license_status_var = tk.StringVar(value="UNVERIFIED")
        self.queue_count_var = tk.StringVar(value="0 TASKS")
        self.countdown_var = tk.StringVar(value="CHƯA KÍCH HOẠT")
        self.user_name_var = tk.StringVar(value="")
        self.is_licensed = False

        # Countdown timer state
        self._expires_at: Optional[datetime] = None
        self._countdown_job_id: Optional[str] = None

        # iOS Dynamic Island banner ref
        self._ios_banner: Optional[tk.Frame] = None

        # Auto-save non-key settings on change
        for var in (self.save_dir_var, self.threads_var, self.max_ps_var):
            var.trace_add("write", lambda *_: self._autosave_config())

        # Setup UI
        self._setup_ttk_styles()
        self._build_ui()
        self._set_ui_frozen(True)
        self._poll_queues()

        # Bind window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Auto-check for updates on startup
        if startup_checks:
            self.root.after(400, self.check_for_updates)

        # Auto-verify license on startup if saved
        if startup_checks and self.license_var.get().strip():
            self.root.after(800, lambda: self.verify_license_background(silent=True))

    # --------------------------------------------------------------------------
    # Config Persistence
    # --------------------------------------------------------------------------
    def _load_config(self) -> Dict[str, Any]:
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_valid_license(self, key: str) -> None:
        self._cfg["license_key"] = key.strip()
        self._autosave_config()

    def _autosave_config(self) -> None:
        try:
            threads_val = int(self.threads_var.get() or 6)
        except ValueError:
            threads_val = 6
        try:
            max_ps_val = int(self.max_ps_var.get() or 3)
        except ValueError:
            max_ps_val = 3

        cfg = {
            "server_url": self.server_var.get().strip() or "http://103.74.103.68:8080",
            "license_key": self._cfg.get("license_key", "").strip(),
            "save_dir": self.save_dir_var.get().strip(),
            "threads": threads_val,
            "max_ps": max_ps_val,
        }
        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def _on_close(self) -> None:
        if self._countdown_job_id:
            try:
                self.root.after_cancel(self._countdown_job_id)
            except Exception:
                pass
        self._autosave_config()
        self.root.destroy()

    # --------------------------------------------------------------------------
    # UI Styling & Component Factories
    # --------------------------------------------------------------------------
    def _setup_ttk_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        # Treeview
        style.configure(
            "Mystic.Treeview",
            background=THEME["CARD"],
            foreground=THEME["TEXT"],
            fieldbackground=THEME["CARD"],
            borderwidth=0,
            rowheight=32,
            font=THEME["FONT_BODY"],
        )
        style.configure(
            "Mystic.Treeview.Heading",
            background=THEME["CARD_HEADER"],
            foreground=THEME["TEXT_MUTED"],
            relief="flat",
            borderwidth=0,
            padding=(10, 8),
            font=THEME["FONT_LABEL"],
        )
        style.map(
            "Mystic.Treeview",
            background=[("selected", THEME["ROW_SEL"])],
            foreground=[("selected", THEME["TEXT"])],
        )
        style.map(
            "Mystic.Treeview.Heading",
            background=[("active", THEME["SEC_BG"])],
            foreground=[("active", THEME["TEXT"])],
        )

        # Scrollbar
        style.configure(
            "Mystic.Vertical.TScrollbar",
            gripcount=0,
            background=THEME["SEC_BG"],
            darkcolor=THEME["CARD"],
            lightcolor=THEME["CARD"],
            troughcolor=THEME["CARD"],
            bordercolor=THEME["CARD"],
            arrowcolor=THEME["TEXT_MUTED"],
            relief="flat",
        )
        style.map(
            "Mystic.Vertical.TScrollbar",
            background=[("active", THEME["SEC_HOVER"]), ("!disabled", THEME["SEC_BG"])],
        )

        # Progressbar
        style.configure(
            "Mystic.Horizontal.TProgressbar",
            background=THEME["SUCCESS"],
            troughcolor=THEME["INPUT_BG"],
            borderwidth=0,
            thickness=6,
        )

    # --------------------------------------------------------------------------
    # UI Building Blocks
    # --------------------------------------------------------------------------
    def _card(self, parent: tk.Misc, title: str, right_var: Optional[tk.StringVar] = None) -> tk.Frame:
        wrapper = tk.Frame(
            parent,
            bg=THEME["CARD"],
            highlightthickness=1,
            highlightbackground=THEME["BORDER"],
        )
        header_bar = tk.Frame(wrapper, bg=THEME["CARD_HEADER"], padx=16, pady=9)
        header_bar.pack(fill="x")

        # Accent square
        dot = tk.Label(header_bar, text="■", font=("Helvetica Neue" if IS_MAC else "Segoe UI", 7), fg=THEME["TEXT"], bg=THEME["CARD_HEADER"])
        dot.pack(side="left", padx=(0, 7))

        lbl = tk.Label(
            header_bar,
            text=title.upper(),
            font=THEME["FONT_CARD_TITLE"],
            fg=THEME["TEXT"],
            bg=THEME["CARD_HEADER"],
        )
        lbl.pack(side="left")

        if right_var is not None:
            badge = tk.Label(
                header_bar,
                textvariable=right_var,
                font=THEME["FONT_CODE"],
                fg=THEME["TEXT_MUTED"],
                bg=THEME["CARD_HEADER"],
            )
            badge.pack(side="right")

        divider = tk.Frame(wrapper, bg=THEME["BORDER"], height=1)
        divider.pack(fill="x")
        return wrapper

    def _field_label(self, parent: tk.Misc, text: str) -> tk.Label:
        return tk.Label(
            parent,
            text=text.upper(),
            font=THEME["FONT_LABEL"],
            fg=THEME["TEXT_MUTED"],
            bg=THEME["CARD"],
        )

    def _entry(
        self,
        parent: tk.Misc,
        var: tk.StringVar,
        width: int = 28,
        show: str = "",
        mono: bool = False,
    ) -> Tuple[tk.Frame, tk.Entry]:
        box = tk.Frame(
            parent,
            bg=THEME["INPUT_BG"],
            highlightthickness=1,
            highlightbackground=THEME["BORDER"],
            padx=10,
            pady=6,
        )
        ent = tk.Entry(
            box,
            textvariable=var,
            width=width,
            show=show,
            font=THEME["FONT_CODE"] if mono else THEME["FONT_BODY"],
            bg=THEME["INPUT_BG"],
            fg=THEME["TEXT"],
            insertbackground=THEME["TEXT"],
            selectbackground="#3F3F46",
            selectforeground=THEME["TEXT"],
            relief="flat",
            bd=0,
        )
        ent.pack(fill="x", expand=True)

        ent.bind("<FocusIn>", lambda _: box.configure(highlightbackground=THEME["BORDER_FOCUS"]))
        ent.bind("<FocusOut>", lambda _: box.configure(highlightbackground=THEME["BORDER"]))
        return box, ent

    def _spinbox(self, parent: tk.Misc, var: tk.StringVar, from_: int, to: int, width: int = 5) -> Tuple[tk.Frame, tk.Spinbox]:
        box = tk.Frame(
            parent,
            bg=THEME["INPUT_BG"],
            highlightthickness=1,
            highlightbackground=THEME["BORDER"],
            padx=8,
            pady=5,
        )
        sp = tk.Spinbox(
            box,
            from_=from_,
            to=to,
            textvariable=var,
            width=width,
            font=THEME["FONT_CODE"],
            bg=THEME["INPUT_BG"],
            fg=THEME["TEXT"],
            insertbackground=THEME["TEXT"],
            buttonbackground=THEME["SEC_BG"],
            relief="flat",
            bd=0,
            justify="center",
        )
        sp.pack(fill="x", expand=True)
        sp.bind("<FocusIn>", lambda _: box.configure(highlightbackground=THEME["BORDER_FOCUS"]))
        sp.bind("<FocusOut>", lambda _: box.configure(highlightbackground=THEME["BORDER"]))
        return box, sp

    def _button(
        self,
        parent: tk.Misc,
        text: str,
        command: Any,
        variant: str = "primary",
        width: Optional[int] = None,
    ) -> tk.Button:
        if variant == "primary":
            bg, fg, hover_bg, border = (
                THEME["PRIMARY_BG"],
                THEME["PRIMARY_FG"],
                THEME["PRIMARY_HOVER"],
                THEME["PRIMARY_BG"],
            )
        elif variant == "danger":
            bg, fg, hover_bg, border = (
                THEME["DANGER_BG"],
                THEME["DANGER_FG"],
                THEME["DANGER_HOVER"],
                "#451A20",
            )
        else:
            bg, fg, hover_bg, border = (
                THEME["SEC_BG"],
                THEME["SEC_FG"],
                THEME["SEC_HOVER"],
                THEME["BORDER"],
            )

        btn = BUTTON_CLASS(
            parent,
            text=text,
            command=command,
            font=THEME["FONT_BTN"],
            bg=bg,
            fg=fg,
            activebackground=hover_bg,
            activeforeground=fg,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=border,
            padx=14,
            pady=6,
            cursor="hand2",
        )
        if width:
            btn.configure(width=width)

        btn.bind("<Enter>", lambda _: btn.configure(bg=hover_bg))
        btn.bind("<Leave>", lambda _: btn.configure(bg=bg))
        return btn

    def _set_ui_frozen(self, frozen: bool) -> None:
        """Freezes or unfreezes all download controls until key verification succeeds."""
        state = "disabled" if frozen else "normal"

        if hasattr(self, "url_entry"):
            self.url_entry.configure(state=state)
        if hasattr(self, "dir_entry"):
            self.dir_entry.configure(state=state)
        if hasattr(self, "sp_thr"):
            self.sp_thr.configure(state=state)
        if hasattr(self, "sp_ps"):
            self.sp_ps.configure(state=state)

        if hasattr(self, "add_btn"):
            if frozen:
                self.add_btn.configure(
                    state="disabled",
                    bg=THEME["INPUT_BG"],
                    fg=THEME["TEXT_MUTED"],
                    cursor="arrow",
                )
            else:
                self.add_btn.configure(
                    state="normal",
                    bg=THEME["PRIMARY_BG"],
                    fg=THEME["PRIMARY_FG"],
                    cursor="hand2",
                )

        if hasattr(self, "browse_btn"):
            if frozen:
                self.browse_btn.configure(
                    state="disabled",
                    bg=THEME["INPUT_BG"],
                    fg=THEME["TEXT_MUTED"],
                    cursor="arrow",
                )
            else:
                self.browse_btn.configure(
                    state="normal",
                    bg=THEME["SEC_BG"],
                    fg=THEME["SEC_FG"],
                    cursor="hand2",
                )

        if hasattr(self, "open_folder_btn"):
            if frozen:
                self.open_folder_btn.configure(
                    state="disabled",
                    bg=THEME["INPUT_BG"],
                    fg=THEME["TEXT_MUTED"],
                    cursor="arrow",
                )
            else:
                self.open_folder_btn.configure(
                    state="normal",
                    bg=THEME["SEC_BG"],
                    fg=THEME["SEC_FG"],
                    cursor="hand2",
                )

        if hasattr(self, "cancel_task_btn"):
            if frozen:
                self.cancel_task_btn.configure(
                    state="disabled",
                    bg=THEME["INPUT_BG"],
                    fg=THEME["TEXT_MUTED"],
                    cursor="arrow",
                )
            else:
                self.cancel_task_btn.configure(
                    state="normal",
                    bg=THEME["DANGER_BG"],
                    fg=THEME["DANGER_FG"],
                    cursor="hand2",
                )

        if hasattr(self, "clear_finished_btn"):
            if frozen:
                self.clear_finished_btn.configure(
                    state="disabled",
                    bg=THEME["INPUT_BG"],
                    fg=THEME["TEXT_MUTED"],
                    cursor="arrow",
                )
            else:
                self.clear_finished_btn.configure(
                    state="normal",
                    bg=THEME["SEC_BG"],
                    fg=THEME["SEC_FG"],
                    cursor="hand2",
                )

        if hasattr(self, "lock_hint_lbl"):
            if frozen:
                self.lock_hint_lbl.configure(
                    text="🔒 CHƯA KÍCH HOẠT: Vui lòng nhập key và nhấn ACTIVATE để mở khóa chức năng tải",
                    fg=THEME["WARNING"],
                )
            else:
                self.lock_hint_lbl.configure(
                    text="🔓 BẢN QUYỀN HỢP LỆ: Toàn bộ chức năng tải và hàng đợi đã sẵn sàng",
                    fg=THEME["SUCCESS"],
                )

    # --------------------------------------------------------------------------
    # Main Layout Construction
    # --------------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=3)  # Queue card
        self.root.rowconfigure(3, weight=2)  # Log card

        # 1. Header Bar
        self._build_header()

        # 2. Top Grid: Left = License & Connection, Right = Add Task
        top_grid = tk.Frame(self.root, bg=THEME["BG"])
        top_grid.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 12))
        top_grid.columnconfigure(0, weight=5)
        top_grid.columnconfigure(1, weight=7)

        self._build_creds_card(top_grid)
        self._build_add_card(top_grid)

        # 3. Queue Card
        self._build_queue_card(self.root)

        # 4. Activity Log Card
        self._build_log_card(self.root)

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=THEME["BG"], pady=14)
        header.grid(row=0, column=0, sticky="ew", padx=20)

        # Left Brand
        brand_frame = tk.Frame(header, bg=THEME["BG"])
        brand_frame.pack(side="left")

        accent_bar = tk.Frame(brand_frame, bg=THEME["TEXT"], width=4, height=34)
        accent_bar.pack(side="left", padx=(0, 12))

        title_stack = tk.Frame(brand_frame, bg=THEME["BG"])
        title_stack.pack(side="left")

        title_lbl = tk.Label(
            title_stack,
            text=f"AutoHDR Download v{APP_VERSION}",
            font=THEME["FONT_BRAND"],
            fg=THEME["TEXT"],
            bg=THEME["BG"],
        )
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(
            title_stack,
            text="HIGH-SPEED CLOUD ASSET DOWNLOADER  •  ANTI-CRACK ARCHITECTURE",
            font=THEME["FONT_SUBBRAND"],
            fg=THEME["TEXT_MUTED"],
            bg=THEME["BG"],
        )
        sub_lbl.pack(anchor="w")

        # Right Status Badges
        right_bar = tk.Frame(header, bg=THEME["BG"])
        right_bar.pack(side="right")

        # License Status Badge
        self.status_lbl = tk.Label(
            right_bar,
            textvariable=self.license_status_var,
            font=THEME["FONT_CODE"],
            fg=THEME["TEXT_MUTED"],
            bg=THEME["CARD"],
            padx=12,
            pady=6,
            highlightthickness=1,
            highlightbackground=THEME["BORDER"],
        )
        self.status_lbl.pack(side="left", padx=(0, 10))

        # HWID Pill (Clickable to copy)
        hwid_short = f"HWID: {self.hwid[:8]}…{self.hwid[-6:]}"
        hwid_btn = BUTTON_CLASS(
            right_bar,
            text=f"⧉  {hwid_short}",
            command=self._copy_hwid,
            font=THEME["FONT_CODE"],
            fg=THEME["TEXT"],
            bg=THEME["CARD"],
            activebackground=THEME["SEC_HOVER"],
            activeforeground=THEME["TEXT"],
            relief="flat",
            bd=0,
            padx=12,
            pady=6,
            highlightthickness=1,
            highlightbackground=THEME["BORDER"],
            cursor="hand2",
        )
        hwid_btn.pack(side="left")

    def _copy_hwid(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.hwid)
        self.append_log(f"Copied full HWID to clipboard: {self.hwid}", "info")

    def _build_creds_card(self, parent: tk.Misc) -> None:
        card = self._card(parent, "License Activation")
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        body = tk.Frame(card, bg=THEME["CARD"], padx=16, pady=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        # Row 0: License Key Label
        self._field_label(body, "License Key").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))

        # Row 1: License Key Input + Show + Activate
        key_box, self.key_entry = self._entry(body, self.license_var, show="•", mono=True)
        key_box.grid(row=1, column=0, sticky="ew", padx=(0, 6), pady=(0, 10))

        def toggle_key():
            self.key_entry.configure(show="" if self.key_entry.cget("show") == "•" else "•")

        eye_btn = self._button(body, "SHOW", toggle_key, variant="secondary")
        eye_btn.grid(row=1, column=1, padx=(0, 6), pady=(0, 10))

        verify_btn = self._button(body, "ACTIVATE KEY", lambda: self.verify_license_background(silent=False), variant="primary")
        verify_btn.grid(row=1, column=2, sticky="e", pady=(0, 10))

        # Row 2: Lock / Ready Banner + Countdown
        self.lock_hint_frame = tk.Frame(
            body,
            bg=THEME["INPUT_BG"],
            highlightthickness=1,
            highlightbackground=THEME["BORDER"],
            padx=12,
            pady=10,
        )
        self.lock_hint_frame.grid(row=2, column=0, columnspan=3, sticky="ew")

        self.lock_hint_lbl = tk.Label(
            self.lock_hint_frame,
            text="🔒 CHƯA KÍCH HOẠT: Vui lòng nhập key và nhấn ACTIVATE để mở khóa chức năng tải",
            font=THEME["FONT_SUBBRAND"],
            fg=THEME["WARNING"],
            bg=THEME["INPUT_BG"],
            anchor="w",
        )
        self.lock_hint_lbl.pack(side="left", fill="x", expand=True)

    def _build_add_card(self, parent: tk.Misc) -> None:
        card = self._card(parent, "New Download Task & Engine Settings")
        card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        body = tk.Frame(card, bg=THEME["CARD"], padx=16, pady=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        # Row 0-1: URL Input + Download Button
        self._field_label(body, "Photoshoot URL or UUID").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))

        self.url_box, self.url_entry = self._entry(body, self.url_var)
        self.url_box.grid(row=1, column=0, columnspan=3, sticky="ew", padx=(0, 8), pady=(0, 10))
        self.url_entry.bind("<Return>", lambda _: self.add_download_task())

        self.add_btn = self._button(body, "DOWNLOAD", self.add_download_task, variant="primary")
        self.add_btn.grid(row=1, column=3, sticky="ew", pady=(0, 10))

        # Row 2-3: Output Folder + Browse + Threads + Concurrent
        self._field_label(body, "Output Folder").grid(row=2, column=0, sticky="w", pady=(0, 4))
        self._field_label(body, "Threads").grid(row=2, column=2, sticky="w", padx=(8, 0), pady=(0, 4))
        self._field_label(body, "Concurrent").grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(0, 4))

        self.dir_box, self.dir_entry = self._entry(body, self.save_dir_var)
        self.dir_box.grid(row=3, column=0, sticky="ew", padx=(0, 6))

        self.browse_btn = self._button(body, "BROWSE", self._browse_save_dir, variant="secondary")
        self.browse_btn.grid(row=3, column=1, padx=(0, 4))

        self.sp_thr_box, self.sp_thr = self._spinbox(body, self.threads_var, from_=1, to=32, width=5)
        self.sp_thr_box.grid(row=3, column=2, sticky="ew", padx=(8, 4))

        self.sp_ps_box, self.sp_ps = self._spinbox(body, self.max_ps_var, from_=1, to=10, width=5)
        self.sp_ps_box.grid(row=3, column=3, sticky="ew", padx=(8, 0))

    def _build_queue_card(self, parent: tk.Misc) -> None:
        card = self._card(parent, "Download Queue", right_var=self.queue_count_var)
        card.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 12))

        body = tk.Frame(card, bg=THEME["CARD"])
        body.pack(fill="both", expand=True, padx=16, pady=12)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        cols = ("id", "title", "status", "progress", "speed", "files")
        self.tree = ttk.Treeview(
            body,
            columns=cols,
            show="headings",
            style="Mystic.Treeview",
            selectmode="browse",
        )

        self.tree.heading("id", text="#")
        self.tree.heading("title", text="PHOTOSHOOT ADDRESS / TITLE", anchor="w")
        self.tree.heading("status", text="STATUS", anchor="w")
        self.tree.heading("progress", text="PROGRESS")
        self.tree.heading("speed", text="SPEED")
        self.tree.heading("files", text="FILES (DL / SKIP / FAIL)")

        self.tree.column("id", width=48, anchor="center", stretch=False)
        self.tree.column("title", width=380, anchor="w")
        self.tree.column("status", width=180, anchor="w")
        self.tree.column("progress", width=110, anchor="center", stretch=False)
        self.tree.column("speed", width=110, anchor="center", stretch=False)
        self.tree.column("files", width=170, anchor="center", stretch=False)

        # Zebra rows & status tags
        self.tree.tag_configure("odd", background=THEME["CARD"])
        self.tree.tag_configure("even", background=THEME["ROW_ALT"])
        self.tree.tag_configure("completed_row", foreground="#10B981")

        tree_scroll = ttk.Scrollbar(
            body,
            orient="vertical",
            command=self.tree.yview,
            style="Mystic.Vertical.TScrollbar",
        )
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll.grid(row=0, column=1, sticky="ns")

        # Click on "✔ XONG [📂 MỞ]" cell -> Open folder immediately
        def on_tree_click(event):
            region = self.tree.identify_region(event.x, event.y)
            if region != "cell":
                return
            col = self.tree.identify_column(event.x)
            row_id = self.tree.identify_row(event.y)
            if not row_id:
                return
            job = self._job_rows.get(row_id)
            if not job:
                return
            if col == "#3" and any(k in job.status for k in ("✔", "XONG", "MỞ", "Done")):
                if job.folder_path and job.folder_path.exists():
                    open_folder(job.folder_path)
                    self.append_log(f"Opened folder: {job.folder_path}", "success")
                else:
                    base_dir = Path(self.save_dir_var.get())
                    if base_dir.exists():
                        open_folder(base_dir)

        def on_tree_motion(event):
            region = self.tree.identify_region(event.x, event.y)
            if region == "cell":
                col = self.tree.identify_column(event.x)
                row_id = self.tree.identify_row(event.y)
                if row_id and col == "#3":
                    job = self._job_rows.get(row_id)
                    if job and any(k in job.status for k in ("✔", "XONG", "MỞ", "Done")):
                        self.tree.configure(cursor="hand2")
                        return
            self.tree.configure(cursor="")

        def on_tree_double_click(event):
            row_id = self.tree.identify_row(event.y)
            if not row_id:
                return
            job = self._job_rows.get(row_id)
            if job and job.folder_path and job.folder_path.exists():
                open_folder(job.folder_path)
                self.append_log(f"Opened folder: {job.folder_path}", "success")

        self.tree.bind("<ButtonRelease-1>", on_tree_click)
        self.tree.bind("<Motion>", on_tree_motion)
        self.tree.bind("<Double-1>", on_tree_double_click)

        # Action bar under queue
        action_bar = tk.Frame(card, bg=THEME["CARD"], padx=16, pady=10)
        action_bar.pack(fill="x")

        self.open_folder_btn = self._button(action_bar, "OPEN FOLDER", self.open_selected_folder, variant="secondary")
        self.open_folder_btn.pack(side="left", padx=(0, 8))
        self.cancel_task_btn = self._button(action_bar, "CANCEL TASK", self.cancel_selected_job, variant="danger")
        self.cancel_task_btn.pack(side="left", padx=(0, 8))
        self.clear_finished_btn = self._button(action_bar, "CLEAR FINISHED", self.clear_completed_jobs, variant="secondary")
        self.clear_finished_btn.pack(side="left")

    def _build_log_card(self, parent: tk.Misc) -> None:
        card = self._card(parent, "Live System Activity Log")
        card.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 16))

        body = tk.Frame(card, bg=THEME["INPUT_BG"])
        body.pack(fill="both", expand=True, padx=16, pady=12)

        self.log_text = tk.Text(
            body,
            bg=THEME["INPUT_BG"],
            fg=THEME["TEXT"],
            insertbackground=THEME["TEXT"],
            font=THEME["FONT_CODE"],
            relief="flat",
            bd=0,
            wrap="word",
            state="disabled",
            height=6,
        )
        scroll = ttk.Scrollbar(
            body,
            orient="vertical",
            command=self.log_text.yview,
            style="Mystic.Vertical.TScrollbar",
        )
        self.log_text.configure(yscrollcommand=scroll.set)

        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # Tag styles
        self.log_text.tag_config("info", foreground=THEME["TEXT_MUTED"])
        self.log_text.tag_config("success", foreground=THEME["SUCCESS"])
        self.log_text.tag_config("warn", foreground=THEME["WARNING"])
        self.log_text.tag_config("error", foreground=THEME["ERROR"])
        self.log_text.tag_config("ts", foreground="#52525B")

    # --------------------------------------------------------------------------
    # Logging & Queue Polling (Thread-safe UI updates)
    # --------------------------------------------------------------------------
    def call_on_ui(self, callback) -> None:
        """Workers enqueue UI work; only the Tk main thread touches Cocoa/Tcl."""
        self._ui_queue.put(callback)

    def append_log(self, message: str, tag: str = "info") -> None:
        self._log_queue.put((message, tag))

    def _poll_queues(self) -> None:
        while not self._ui_queue.empty():
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                self.root.report_callback_exception(*sys.exc_info())

        # Flush logs
        while not self._log_queue.empty():
            try:
                msg, tag = self._log_queue.get_nowait()
                ts = datetime.now().strftime("%H:%M:%S")
                self.log_text.configure(state="normal")
                self.log_text.insert("end", f"[{ts}] ", "ts")
                self.log_text.insert("end", f"{msg}\n", tag)
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
            except queue.Empty:
                break

        # Flush progress updates
        while not self._progress_queue.empty():
            try:
                job = self._progress_queue.get_nowait()
                self._update_tree_row(job)
            except queue.Empty:
                break

        self.root.after(100, self._poll_queues)

    def _refresh_queue_counter(self) -> None:
        active = sum(1 for j in self.jobs if not any(k in j.status for k in ("Completed", "Done", "XONG", "Cancelled", "Error")))
        self.queue_count_var.set(f"{active} RUNNING / {len(self.jobs)} TOTAL")

    # --------------------------------------------------------------------------
    # iOS Dynamic Island Slide-down Welcome Banner
    # --------------------------------------------------------------------------
    def _show_ios_welcome_banner(self, user_name: str) -> None:
        """Slides down an iPhone Dynamic Island banner welcoming the customer."""
        if self._ios_banner and self._ios_banner.winfo_exists():
            try:
                self._ios_banner.destroy()
            except Exception:
                pass
            self._ios_banner = None

        name = user_name.strip()
        greeting = f"Chào mừng {name}!" if name else "Chào mừng bạn!"

        # Pill-shaped Dynamic Island container
        island = tk.Frame(
            self.root,
            bg="#0E0E12",
            highlightthickness=1,
            highlightbackground="#2C2C38",
            padx=18,
            pady=10,
            cursor="hand2",
        )
        self._ios_banner = island

        # Click anywhere on island to dismiss early
        island.bind("<Button-1>", lambda _: self._dismiss_ios_banner(island))

        # Left glowing check icon circle
        icon_frame = tk.Frame(island, bg="#16161E", width=34, height=34)
        icon_frame.pack(side="left", padx=(0, 14))
        icon_frame.pack_propagate(False)
        icon_lbl = tk.Label(icon_frame, text="✓", font=("Helvetica Neue" if IS_MAC else "Segoe UI", 12, "bold"), fg="#10B981", bg="#16161E")
        icon_lbl.pack(expand=True)
        icon_lbl.bind("<Button-1>", lambda _: self._dismiss_ios_banner(island))

        # Text stack
        text_stack = tk.Frame(island, bg="#0E0E12")
        text_stack.pack(side="left", fill="both", expand=True)
        text_stack.bind("<Button-1>", lambda _: self._dismiss_ios_banner(island))

        title_lbl = tk.Label(
            text_stack,
            text=greeting,
            font=("Helvetica Neue" if IS_MAC else "Segoe UI Semibold", 10, "bold"),
            fg="#FFFFFF",
            bg="#0E0E12",
            anchor="w",
        )
        title_lbl.pack(anchor="w")
        title_lbl.bind("<Button-1>", lambda _: self._dismiss_ios_banner(island))

        sub_lbl = tk.Label(
            text_stack,
            text="Đã kích hoạt bản quyền thành công • AutoHDR VIP",
            font=("Helvetica Neue" if IS_MAC else "Segoe UI", 8),
            fg="#9CA3AF",
            bg="#0E0E12",
            anchor="w",
        )
        sub_lbl.pack(anchor="w")
        sub_lbl.bind("<Button-1>", lambda _: self._dismiss_ios_banner(island))

        # Right status tag
        tag_lbl = tk.Label(
            island,
            text="ACTIVE",
            font=("Helvetica Neue" if IS_MAC else "Segoe UI Semibold", 8),
            fg="#10B981",
            bg="#162620",
            padx=8,
            pady=2,
            highlightthickness=1,
            highlightbackground="#1E3A2F",
        )
        tag_lbl.pack(side="right", padx=(14, 0))
        tag_lbl.bind("<Button-1>", lambda _: self._dismiss_ios_banner(island))

        # Start off-screen above top center
        island.place(relx=0.5, y=-70, anchor="n")
        island.lift()

        target_y = 18
        current_y = -70

        def slide_down():
            nonlocal current_y
            if not island.winfo_exists():
                return
            diff = target_y - current_y
            if diff > 1:
                step = max(2, int(diff * 0.35))
                current_y += step
                island.place_configure(y=current_y)
                self.root.after(16, slide_down)
            else:
                current_y = target_y
                island.place_configure(y=current_y)
                # Hold for 3 seconds then slide up
                self.root.after(3000, lambda: self._dismiss_ios_banner(island))

        self.root.after(20, slide_down)

    def _dismiss_ios_banner(self, island: tk.Frame) -> None:
        if not island.winfo_exists():
            return
        target_y = -80
        try:
            current_y = int(island.place_info().get("y", 18))
        except Exception:
            current_y = 18

        def slide_up():
            nonlocal current_y
            if not island.winfo_exists():
                return
            diff = current_y - target_y
            if diff > 1:
                step = max(2, int(diff * 0.35))
                current_y -= step
                island.place_configure(y=current_y)
                self.root.after(16, slide_up)
            else:
                island.destroy()
                if self._ios_banner == island:
                    self._ios_banner = None

        slide_up()

    # --------------------------------------------------------------------------
    # License Validation & Real-time Countdown Timer
    # --------------------------------------------------------------------------
    def verify_license_background(self, silent: bool = False) -> None:
        key = self.license_var.get().strip()
        server = self.server_var.get().strip().rstrip("/")
        if not server.startswith("http://") and not server.startswith("https://"):
            server = f"http://{server}"

        if not key:
            self.is_licensed = False
            self.license_status_var.set("MISSING KEY")
            self.status_lbl.configure(fg=THEME["ERROR"], highlightbackground=THEME["ERROR"])
            self.countdown_var.set("CHƯA NHẬP KEY")
            self._set_ui_frozen(True)
            if not silent:
                messagebox.showwarning("Yêu cầu nhập key", "Vui lòng nhập License Key.")
            return

        self.license_status_var.set("VERIFYING…")
        self.status_lbl.configure(fg=THEME["TEXT"], highlightbackground=THEME["BORDER_FOCUS"])

        def worker():
            import urllib.request
            import urllib.error

            url = f"{server}/api/license/verify"
            payload = json.dumps({"key": key, "hwid": self.hwid}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10, context=ssl_context()) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    exp = data.get("expires_at", "Active")
                    user = data.get("user", "")

                    def accept_license():
                        self.is_licensed = True
                        self._save_valid_license(key)
                        self.user_name_var.set(f"Khách hàng: {user}" if user else "")
                        self._setup_license_countdown(exp, user)
                        self._show_ios_welcome_banner(user)

                    self.call_on_ui(accept_license)

                    self.append_log(f"License verified: {user or 'Valid'} ({exp})", "success")
                    if not silent:
                        self.call_on_ui(lambda: messagebox.showinfo(
                            "Kích hoạt thành công",
                            f"Bản quyền hợp lệ!\nNgười dùng: {user or 'Khách hàng'}\nThời hạn: {exp}"
                        ))
            except urllib.error.HTTPError as e:
                self.is_licensed = False
                self.call_on_ui(self._stop_countdown)
                try:
                    err_data = json.loads(e.read().decode("utf-8"))
                    err_msg = err_data.get("error") or str(e)
                except Exception:
                    err_msg = str(e)

                err_lower = err_msg.lower()
                if "expired" in err_lower:
                    status_text = "✕ EXPIRED"
                    popup_title = "Bản quyền hết hạn"
                    popup_msg = "Khóa bản quyền của bạn đã hết hạn sử dụng!\nVui lòng liên hệ quản trị viên để gia hạn key mới."
                    self.call_on_ui(lambda: self.countdown_var.set("✕ BẢN QUYỀN ĐÃ HẾT HẠN"))
                    self.call_on_ui(lambda: messagebox.showwarning(popup_title, popup_msg))
                elif any(k in err_lower for k in ("hwid", "hardware", "mismatch", "limit", "machine", "computer")):
                    status_text = "✕ HWID LIMIT"
                    popup_title = "Giới hạn thiết bị"
                    popup_msg = f"{err_msg}\nVui lòng liên hệ quản trị viên để nâng thêm số máy hoặc reset thiết bị."
                    self.call_on_ui(lambda: self.countdown_var.set("✕ SAI THIẾT BỊ (HWID)"))
                    if not silent:
                        self.call_on_ui(lambda: messagebox.showerror(popup_title, popup_msg))
                elif "not exist" in err_lower or "invalid" in err_lower:
                    status_text = "✕ INVALID KEY"
                    popup_title = "Key không hợp lệ"
                    popup_msg = "Mã bản quyền không tồn tại trên hệ thống."
                    self.call_on_ui(lambda: self.countdown_var.set("✕ KEY KHÔNG HỢP LỆ"))
                    if not silent:
                        self.call_on_ui(lambda: messagebox.showerror(popup_title, popup_msg))
                else:
                    status_text = f"✕ {err_msg.upper()[:16]}"
                    popup_title = "Lỗi xác thực"
                    popup_msg = f"Lỗi xác thực bản quyền: {err_msg}"
                    self.call_on_ui(lambda: self.countdown_var.set(f"✕ {err_msg}"))
                    if not silent:
                        self.call_on_ui(lambda: messagebox.showerror(popup_title, popup_msg))

                self.call_on_ui(lambda: self._set_license_error(status_text))
                self.append_log(f"License check failed: {err_msg}", "error")
            except Exception as e:
                self.is_licensed = False
                self.call_on_ui(self._stop_countdown)
                self.call_on_ui(lambda: self._set_license_error("✕ SERVER OFFLINE"))
                self.call_on_ui(lambda: self.countdown_var.set("✕ MÁY CHỦ NGOẠI TUYẾN"))
                self.append_log(f"Cannot reach VPS server: {e}", "error")
                if not silent:
                    self.call_on_ui(lambda: messagebox.showerror(
                        "Lỗi máy chủ",
                        f"Không thể kết nối đến máy chủ bảo mật ({server}).\nVui lòng kiểm tra lại kết nối mạng hoặc trạng thái VPS."
                    ))

        threading.Thread(target=worker, daemon=True).start()

    def _setup_license_countdown(self, exp_str: str, user: str) -> None:
        """Parses expires_at and starts real-time countdown timer."""
        self._stop_countdown()

        if not exp_str or any(k in str(exp_str).lower() for k in ("lifetime", "vĩnh viễn", "active")):
            self._expires_at = None
            self.call_on_ui(lambda: self.countdown_var.set("BẢN QUYỀN VĨNH VIỄN (LIFETIME)"))
            lbl = f"● ACTIVE: {user} (LIFETIME)" if user else "● ACTIVE (LIFETIME)"
            self.call_on_ui(lambda: self._set_license_success(lbl))
            return

        # Parse ISO string
        parsed_dt = None
        clean_exp = str(exp_str).strip()
        try:
            if " " in clean_exp and "T" not in clean_exp:
                clean_exp = clean_exp.replace(" ", "T")
            if len(clean_exp) == 16:
                clean_exp += ":00"
            parsed_dt = datetime.fromisoformat(clean_exp)
            if parsed_dt.tzinfo is None:
                parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
        except Exception:
            parsed_dt = None

        if not parsed_dt:
            self._expires_at = None
            self.call_on_ui(lambda: self.countdown_var.set(f"HẾT HẠN: {exp_str}"))
            lbl = f"● ACTIVE: {user} ({exp_str})" if user else f"● ACTIVE ({exp_str})"
            self.call_on_ui(lambda: self._set_license_success(lbl))
            return

        self._expires_at = parsed_dt
        self.call_on_ui(self._update_countdown_tick)

    def _update_countdown_tick(self) -> None:
        """Ticking countdown loop called every 1 second."""
        if not self.is_licensed or not self._expires_at:
            return

        now = datetime.now(timezone.utc) if self._expires_at.tzinfo else datetime.now()
        diff = self._expires_at - now
        total_seconds = int(diff.total_seconds())

        if total_seconds <= 0:
            self.is_licensed = False
            self.countdown_var.set("✕ BẢN QUYỀN ĐÃ HẾT HẠN")
            self._set_license_error("✕ EXPIRED")
            self.append_log("License expiration countdown reached 0. Downloads disabled.", "error")
            messagebox.showwarning("Hết hạn bản quyền", "Khóa bản quyền của bạn đã hết hạn sử dụng!\nVui lòng liên hệ quản trị viên để gia hạn.")
            return

        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if days > 0:
            timer_text = f"{days} ngày {hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            timer_text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        self.countdown_var.set(f"CÒN LẠI: {timer_text}")

        user = self.user_name_var.get().replace("Khách hàng: ", "").strip()
        status_label = f"● ACTIVE: {user} ({timer_text})" if user else f"● ACTIVE ({timer_text})"
        self._set_license_success(status_label)

        # Schedule next tick in 1 second
        self._countdown_job_id = self.root.after(1000, self._update_countdown_tick)

    def _stop_countdown(self) -> None:
        if self._countdown_job_id:
            try:
                self.root.after_cancel(self._countdown_job_id)
            except Exception:
                pass
            self._countdown_job_id = None

    def _set_license_success(self, text: str) -> None:
        self.license_status_var.set(text)
        self.status_lbl.configure(fg=THEME["SUCCESS"], highlightbackground=THEME["SUCCESS"])
        if hasattr(self, "countdown_box_lbl"):
            self.countdown_box_lbl.configure(fg=THEME["SUCCESS"])
        self._set_ui_frozen(False)

    def _set_license_error(self, text: str) -> None:
        self.license_status_var.set(text)
        self.status_lbl.configure(fg=THEME["ERROR"], highlightbackground=THEME["ERROR"])
        if hasattr(self, "countdown_box_lbl"):
            self.countdown_box_lbl.configure(fg=THEME["ERROR"])
        self._set_ui_frozen(True)

    # --------------------------------------------------------------------------
    # Auto-Update System (Mandatory Check & Windows Self-Replace)
    # --------------------------------------------------------------------------
    def check_for_updates(self) -> None:
        """Queries the VPS server to check if a mandatory newer version exists."""
        server = self.server_var.get().strip().rstrip("/")
        if not server.startswith("http://") and not server.startswith("https://"):
            server = f"http://{server}"

        def update_worker():
            import urllib.request
            try:
                url = f"{server}/api/app/version"
                req = urllib.request.Request(url, headers={"User-Agent": "AutoHDR-Updater"})
                with urllib.request.urlopen(req, timeout=6, context=ssl_context()) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if IS_MAC:
                        data = select_release(data, mac_arch())
                        if data is None:
                            return
                    latest_v = data.get("latest_version", "")
                    if latest_v and is_newer_version(latest_v, APP_VERSION):
                        self.call_on_ui(lambda: self._show_mandatory_update_dialog(data))
            except Exception as e:
                # Silently ignore update check errors if offline
                self.append_log(f"Update check completed (running v{APP_VERSION})", "info")

        threading.Thread(target=update_worker, daemon=True).start()

    def _show_mandatory_update_dialog(self, ver_data: Dict[str, Any]) -> None:
        """Displays a modal mandatory update prompt with progress download and auto-replace."""
        if IS_MAC:
            self._show_mac_update_dialog(ver_data)
            return
        download_url = ver_data.get("download_url", "/api/app/download")

        dlg = tk.Toplevel(self.root)
        dlg.title("Thông Báo Cập Nhật")
        dlg.geometry("480x250")
        dlg.resizable(False, False)
        dlg.configure(bg=THEME["BG"])
        dlg.transient(self.root)
        dlg.grab_set()

        # Center on parent window
        self.root.update_idletasks()
        rx = self.root.winfo_x()
        ry = self.root.winfo_y()
        rw = self.root.winfo_width()
        rh = self.root.winfo_height()
        dlg.geometry(f"+{max(0, rx + (rw - 480) // 2)}+{max(0, ry + (rh - 250) // 2)}")

        # Closing/canceling mandatory update exits app
        def on_cancel():
            self.root.destroy()
            sys.exit(0)

        dlg.protocol("WM_DELETE_WINDOW", on_cancel)

        # Header
        hdr_frame = tk.Frame(dlg, bg=THEME["CARD_HEADER"], padx=20, pady=14)
        hdr_frame.pack(fill="x")

        tk.Label(
            hdr_frame,
            text="⚡  THÔNG BÁO CẬP NHẬT",
            font=THEME["FONT_CARD_TITLE"],
            fg=THEME["SUCCESS"],
            bg=THEME["CARD_HEADER"],
        ).pack(anchor="w")

        # Body
        body = tk.Frame(dlg, bg=THEME["BG"], padx=20, pady=20)
        body.pack(fill="both", expand=True)

        msg_lbl = tk.Label(
            body,
            text="Hệ thống đã có bản cập nhật mới.\nĐây là bản cập nhật bắt buộc để tiếp tục sử dụng ứng dụng.",
            font=THEME["FONT_BODY"],
            fg=THEME["TEXT"],
            bg=THEME["BG"],
            justify="left",
        )
        msg_lbl.pack(anchor="w", pady=(0, 10))

        # Progress bar (hidden initially)
        progress_frame = tk.Frame(body, bg=THEME["BG"])
        pbar = ttk.Progressbar(progress_frame, style="Mystic.Horizontal.TProgressbar", length=440, mode="determinate")
        pbar.pack(fill="x", pady=(0, 6))

        status_dl_lbl = tk.Label(
            progress_frame,
            text="Đang chuẩn bị tải...",
            font=THEME["FONT_CODE"],
            fg=THEME["SUCCESS"],
            bg=THEME["BG"],
        )
        status_dl_lbl.pack(anchor="w")

        # Bottom Button Bar
        btn_bar = tk.Frame(dlg, bg=THEME["CARD_HEADER"], padx=20, pady=12)
        btn_bar.pack(fill="x", side="bottom")

        def start_download():
            btn_update.configure(state="disabled")
            btn_quit.configure(state="disabled")
            msg_lbl.pack_forget()
            progress_frame.pack(fill="x", pady=(4, 0))

            server = self.server_var.get().strip().rstrip("/")
            if not server.startswith("http://") and not server.startswith("https://"):
                server = f"http://{server}"

            full_dl_url = download_url
            if not full_dl_url.startswith("http://") and not full_dl_url.startswith("https://"):
                full_dl_url = f"{server}{full_dl_url}"

            threading.Thread(target=download_task, args=(full_dl_url,), daemon=True).start()

        def download_task(url: str):
            import urllib.request
            try:
                exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else BASE_DIR
                # Keep update temp files isolated from user-facing filenames,
                # so replacing the running exe leaves only AutoHDR.exe.
                new_exe = exe_dir / "_update_download.exe"
                tmp_part = exe_dir / "Photoshoot_Download_update.part"

                req = urllib.request.Request(url, headers={"User-Agent": "AutoHDR-Updater"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    total_bytes = int(resp.headers.get("Content-Length", 0))
                    downloaded = 0
                    start_t = time.time()

                    with open(tmp_part, "wb") as out_f:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            out_f.write(chunk)
                            downloaded += len(chunk)

                            # Calculate speed & progress
                            elapsed = time.time() - start_t
                            spd = (downloaded / 1048576) / elapsed if elapsed > 0.5 else 0.0
                            pct = (downloaded / total_bytes) * 100 if total_bytes > 0 else 0

                            # Format MB
                            cur_mb = downloaded / 1048576
                            tot_mb = total_bytes / 1048576
                            msg = f"Đang tải: {pct:.1f}% ({cur_mb:.1f} MB / {tot_mb:.1f} MB) • {spd:.1f} MB/s"
                            self.call_on_ui(lambda p=pct, m=msg: (pbar.configure(value=p), status_dl_lbl.configure(text=m)))

                # Rename part file to new exe
                if tmp_part.exists():
                    tmp_part.replace(new_exe)

                self.call_on_ui(lambda: status_dl_lbl.configure(text="✔ Tải hoàn tất! Đang khởi động lại ứng dụng mới..."))
                time.sleep(1.2)

                # Run Windows self-replacement batch script
                self._apply_update_and_restart(new_exe)

            except Exception as e:
                self.call_on_ui(lambda error=str(e): messagebox.showerror("Lỗi tải cập nhật", f"Không thể tải bản cập nhật mới:\n{error}\nVui lòng thử lại sau."))
                self.call_on_ui(on_cancel)

        btn_quit = self._button(btn_bar, "✕  BỎ QUA (THOÁT)", on_cancel, variant="danger")
        btn_quit.pack(side="right", padx=(8, 0))

        btn_update = self._button(btn_bar, "⚡  CẬP NHẬT NGAY", start_download, variant="primary")
        btn_update.pack(side="right")

    def _show_mac_update_dialog(self, release: Dict[str, Any]) -> None:
        """Download a checked Mac ZIP; installation never modifies the running bundle."""
        required = bool(release.get("required", False))
        prompt = (
            f"Đã có AutoHDR {release['latest_version']} cho macOS ({mac_arch()}).\n\n"
            "Tải ZIP, giải nén rồi thoát AutoHDR và kéo AutoHDR.app mới vào Applications.\n"
            "License và cấu hình được giữ trong Library/Application Support/AutoHDR."
        )
        if not messagebox.askyesno("Cập nhật AutoHDR cho Mac", prompt, parent=self.root):
            if required:
                self._on_close()
            return
        server = self.server_var.get().strip().rstrip("/")
        if not server.startswith(("http://", "https://")):
            server = f"http://{server}"
        self.append_log("Đang tải bản cập nhật macOS…", "info")

        def worker():
            try:
                destination = Path.home() / "Downloads" / "AutoHDR Updates"
                archive = download_release(server, release, destination)

                def completed():
                    subprocess.Popen(["/usr/bin/open", "-R", str(archive)], close_fds=True)
                    messagebox.showinfo(
                        "Đã tải bản cập nhật",
                        f"Đã kiểm tra SHA-256: {archive}\n\n"
                        "Giải nén ZIP, thoát AutoHDR rồi thay AutoHDR.app trong Applications.",
                        parent=self.root,
                    )
                    if required:
                        self._on_close()

                self.call_on_ui(completed)
            except Exception as error:
                self.call_on_ui(lambda message=str(error): messagebox.showerror(
                    "Lỗi cập nhật macOS", message, parent=self.root,
                ))
                if required:
                    self.call_on_ui(self._on_close)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_update_and_restart(self, new_exe: Path) -> None:
        """
        Replaces the running executable with new_exe and starts it.
        A hidden batch file waits for this process to exit, swaps the files, then launches the new exe.
        """
        is_frozen = getattr(sys, "frozen", False)
        current_exe = Path(sys.executable).resolve() if is_frozen else BASE_DIR / "Photoshoot_Download.exe"
        bat_path = current_exe.parent / "_apply_update.bat"

        try:
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(build_update_script(os.getpid(), current_exe, new_exe))


            # Run hidden batch file in a clean env (no _MEIPASS/_PYI vars so the restarted
            # onefile exe unpacks fresh instead of reusing our soon-to-be-deleted temp dir).
            subprocess.Popen(
                ["cmd.exe", "/c", str(bat_path)],
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=clean_child_env(),
                close_fds=True,
            )
        except Exception as e:
            print(f"Error launching update script: {e}")

        # Force quit immediately so file lock is released
        os._exit(0)

    # --------------------------------------------------------------------------
    # Download Task Orchestration
    # --------------------------------------------------------------------------
    def _browse_save_dir(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.save_dir_var.get())
        if folder:
            self.save_dir_var.set(folder)

    def add_download_task(self) -> None:
        if not self.is_licensed:
            if "EXPIRED" in self.license_status_var.get():
                messagebox.showwarning("Bản quyền hết hạn", "Khóa bản quyền đã hết hạn sử dụng.\nVui lòng kích hoạt key mới để tiếp tục tải!")
            else:
                messagebox.showwarning("Yêu cầu bản quyền", "Vui lòng nhập và kích hoạt License Key hợp lệ trước khi tải!")
            return

        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Thiếu dữ liệu", "Vui lòng nhập đường link hoặc UUID photoshoot.")
            return

        key = self.license_var.get().strip()
        if not key:
            messagebox.showerror("Yêu cầu bản quyền", "Vui lòng nhập License Key.")
            return

        save_dir = self.save_dir_var.get().strip()
        if not save_dir:
            save_dir = str(Path.home() / "Downloads" / "AutoHDR")
            self.save_dir_var.set(save_dir)

        try:
            threads = int(self.threads_var.get() or 6)
        except ValueError:
            threads = 6

        job = DownloadJob(
            ps_input=url,
            save_dir=save_dir,
            server_url=self.server_var.get().strip(),
            license_key=key,
            hwid=self.hwid,
            photo_threads=threads,
        )

        job_id = f"job_{len(self.jobs) + 1}"
        job.id_str = job_id
        self.jobs.append(job)
        self._job_rows[job_id] = job

        # Attach thread-safe callbacks
        job.on_progress = lambda j: self._progress_queue.put(j)
        job.on_log = lambda msg, tag: self.append_log(msg, tag)

        row_idx = len(self.tree.get_children())
        row_tag = "even" if row_idx % 2 == 1 else "odd"

        # Add to Treeview
        self.tree.insert(
            "",
            "end",
            iid=job_id,
            tags=(row_tag,),
            values=(
                len(self.jobs),
                job.ps_input,
                job.status,
                "0.0%",
                "0.0 MB/s",
                "0 / 0 / 0",
            ),
        )

        self._refresh_queue_counter()
        self.url_var.set("")
        self.append_log(f"Enqueued job #{len(self.jobs)}: {url}", "info")

        # Refresh semaphore if user changed concurrent count
        try:
            max_ps = int(self.max_ps_var.get() or 3)
        except ValueError:
            max_ps = 3
        self._semaphore = threading.Semaphore(max_ps)

        def run_thread():
            with self._semaphore:
                job.run()

        threading.Thread(target=run_thread, daemon=True).start()

    def _update_tree_row(self, job: DownloadJob) -> None:
        pct = f"{(job.done / job.total) * 100:.1f}%" if job.total > 0 else "0.0%"
        files_str = f"{job.downloaded} / {job.skipped} / {job.failed}" if job.total > 0 else "0 / 0 / 0"
        title_str = job.title or job.ps_input

        status_str = job.status
        if any(k in status_str for k in ("Done", "Completed", "XONG")) and "MỞ" not in status_str:
            status_str = "✔ XONG [📂 MỞ]"
            job.status = status_str

        try:
            idx = self.tree.index(job.id_str)
            base_tag = "even" if idx % 2 == 1 else "odd"
            tags = [base_tag]
            if "✔ XONG" in status_str or "MỞ" in status_str:
                tags.append("completed_row")

            self.tree.item(
                job.id_str,
                tags=tuple(tags),
                values=(
                    idx + 1,
                    title_str,
                    status_str,
                    pct,
                    job.speed_str,
                    files_str,
                ),
            )
        except Exception:
            pass

    def open_selected_folder(self) -> None:
        sel = self.tree.selection()
        if not sel:
            folder = Path(self.save_dir_var.get())
            if folder.exists():
                open_folder(folder)
            return

        job = self._job_rows.get(sel[0])
        if job and job.folder_path and job.folder_path.exists():
            open_folder(job.folder_path)
        else:
            base_dir = Path(self.save_dir_var.get())
            if base_dir.exists():
                open_folder(base_dir)

    def cancel_selected_job(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        job = self._job_rows.get(sel[0])
        if job:
            job.cancel()

    def clear_completed_jobs(self) -> None:
        completed_ids = []
        for iid, job in list(self._job_rows.items()):
            if any(k in job.status for k in ("Completed", "Done", "XONG", "Cancelled", "Error")):
                completed_ids.append(iid)
                del self._job_rows[iid]
                self.tree.delete(iid)

        # Re-number remaining rows
        for idx, iid in enumerate(self.tree.get_children()):
            vals = list(self.tree.item(iid, "values"))
            if vals:
                vals[0] = str(idx + 1)
                self.tree.item(iid, values=vals, tags=("even" if idx % 2 == 1 else "odd",))

        self._refresh_queue_counter()
        self.append_log(f"Cleared {len(completed_ids)} completed/failed tasks from queue.", "info")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    smoke = "--smoke-test" in sys.argv
    application = PhotoshootApp(startup_checks=not smoke)
    if smoke:
        # Exercise the actual GUI and bundled Tcl/Tk without contacting the VPS.
        application.root.update_idletasks()
        application._set_ui_frozen(False)
        application._set_ui_frozen(True)
        application.root.after(300, application.root.destroy)
    application.run()


if __name__ == "__main__":
    main()
