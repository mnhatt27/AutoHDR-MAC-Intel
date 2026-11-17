"""Package on a macOS host, smoke-test the bundle, and create a distributable ZIP."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=("arm64", "x86_64"), required=True)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Run this command on macOS, or use the Build macOS GitHub workflow.")
    if platform.machine() != args.arch:
        parser.error(f"Use a native {args.arch} Python/runner; this Python runs as {platform.machine()}.")
    # Fail early if Python does not provide Tcl/Tk (the application requires it).
    import tkinter
    root = tkinter.Tk()
    root.destroy()

    dist = ROOT / "MAC" / "dist" / args.arch
    work = ROOT / "MAC" / "build" / args.arch
    env = {**os.environ, "AUTOHDR_TARGET_ARCH": args.arch, "MACOSX_DEPLOYMENT_TARGET": "11.0"}
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(dist), "--workpath", str(work),
        str(ROOT / "MAC" / "AutoHDR.spec"),
    ], check=True, cwd=ROOT, env=env)
    application = dist / "AutoHDR.app"
    executable = application / "Contents" / "MacOS" / "AutoHDR"
    subprocess.run(["/usr/bin/lipo", str(executable), "-verify_arch", args.arch], check=True)
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(application)], check=True)
    # A malformed .app or missing bundled Tk must fail the job, not produce an artifact.
    subprocess.run([str(executable), "--smoke-test"], check=True, timeout=45, cwd=dist)

    tree = ast.parse((ROOT / "client_source" / "app.py").read_text(encoding="utf-8"))
    version = next(ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "APP_VERSION" for t in node.targets))
    archive = dist / f"AutoHDR-macOS-{args.arch}.zip"
    # ditto preserves bundle symlinks, executable bits and framework structure.
    subprocess.run([
        "/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
        str(application), str(archive),
    ], check=True)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist / (archive.name + ".sha256")).write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    release = {
        "latest_version": version,
        "required": False,
        "download_url": f"/api/app/download/macos/{args.arch}",
        "sha256": checksum,
        "release_notes": "AutoHDR Download for macOS",
    }
    (dist / f"release-{args.arch}.json").write_text(
        json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(f"Created {archive}")


if __name__ == "__main__":
    main()
