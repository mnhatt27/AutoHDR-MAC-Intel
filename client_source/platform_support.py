"""Small platform boundary shared by the Windows and macOS clients."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import subprocess
import sys
from tkinter import ttk

IS_MAC = sys.platform == "darwin"


def config_path(base_dir: Path) -> Path:
    if IS_MAC:
        # Never write into a signed .app, a read-only DMG, or an App Translocation path.
        return Path.home() / "Library" / "Application Support" / "AutoHDR" / "photoshoot_config.json"
    return base_dir / "photoshoot_config.json"


def mac_arch() -> str:
    """Select updates for the running binary (including Intel under Rosetta)."""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    raise RuntimeError(f"Unsupported macOS architecture: {machine}")


def open_folder(folder: Path) -> None:
    folder = Path(folder).expanduser().resolve()
    if IS_MAC:
        subprocess.Popen(["/usr/bin/open", str(folder)], close_fds=True)
    elif sys.platform == "win32":
        os.startfile(folder)
    else:
        subprocess.Popen(["xdg-open", str(folder)], close_fds=True)


class MacButton(ttk.Button):
    """Clam buttons keep the dark palette visible on Aqua.

    Accept the tk.Button colour options used by the existing UI. Aqua's native
    tk.Button ignores background colours and can render white text on white.
    """

    def __init__(self, parent, **options):
        self._button_style = f"AutoHDR{id(self)}.TButton"
        self._style = ttk.Style(parent)
        super().__init__(parent, style=self._button_style)
        self.configure(**options)

    def configure(self, cnf=None, **options):
        if not options and cnf is None:
            return super().configure()
        if cnf:
            options = {**cnf, **options}
        visual = {}
        for source, dest in (("bg", "background"), ("fg", "foreground"), ("font", "font")):
            if source in options:
                visual[dest] = options.pop(source)
        active_bg = options.pop("activebackground", None)
        active_fg = options.pop("activeforeground", None)
        padx = options.pop("padx", None)
        pady = options.pop("pady", None)
        if padx is not None or pady is not None:
            visual["padding"] = (padx or 0, pady or 0)
        for option in ("bd", "relief", "highlightthickness", "highlightbackground"):
            options.pop(option, None)
        if visual:
            self._style.configure(self._button_style, **visual)
        mapping = {}
        if active_bg is not None:
            mapping["background"] = [("active", active_bg)]
        if active_fg is not None:
            mapping["foreground"] = [("disabled", "#8E8E99"), ("active", active_fg)]
        if mapping:
            self._style.map(self._button_style, **mapping)
        return super().configure(**options)

    config = configure
