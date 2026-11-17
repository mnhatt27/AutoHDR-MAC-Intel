"""Architecture-specific macOS releases, downloaded for manual .app installation."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import tempfile
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import zipfile
from network_support import ssl_context


def select_release(version_info: dict, arch: str):
    # An old VPS only advertises a Windows EXE. Never use it as a Mac update.
    releases = version_info.get("macos", {})
    release = releases.get(arch) if isinstance(releases, dict) else None
    if not isinstance(release, dict):
        return None
    if not release.get("latest_version") or not release.get("download_url"):
        return None
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(release.get("sha256", ""))):
        return None
    return dict(release)


def download_release(server: str, release: dict, destination: Path, progress=None) -> Path:
    url = urljoin(server.rstrip("/") + "/", release["download_url"])
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("The update URL must use HTTP or HTTPS")
    expected = str(release.get("sha256", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("The macOS release has no valid SHA-256 checksum")
    destination.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    # Each download owns its partial file; a failed download never replaces an archive.
    with tempfile.NamedTemporaryFile(dir=destination, suffix=".part", delete=False) as output:
        temporary = Path(output.name)
        try:
            with urlopen(Request(url, headers={"User-Agent": "AutoHDR-Mac-Updater"}), timeout=30, context=ssl_context()) as response:
                total = int(response.headers.get("Content-Length", 0))
                received = 0
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if progress:
                        progress(received, total)
                if total and received != total:
                    raise ValueError("The update download is incomplete")
            output.close()
            if digest.hexdigest() != expected:
                raise ValueError("The update SHA-256 checksum does not match")
            # Validate the container without extracting or executing downloaded content.
            with zipfile.ZipFile(temporary) as archive:
                if not any(name.endswith(".app/Contents/Info.plist") for name in archive.namelist()):
                    raise ValueError("The archive does not contain a macOS app")
                if archive.testzip() is not None:
                    raise ValueError("The update ZIP is damaged")
            target = destination / f"AutoHDR-{expected[:12]}.zip"
            temporary.replace(target)
            return target
        finally:
            output.close()
            temporary.unlink(missing_ok=True)
