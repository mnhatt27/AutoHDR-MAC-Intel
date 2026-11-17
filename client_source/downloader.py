"""
High-Speed Concurrent Downloader Engine
Communicates with VPS Protected API to resolve download tasks and fetches files in parallel.
"""
from __future__ import annotations
import os
import time
import json
import re
import urllib.request
import urllib.parse
import ssl
import sys
from network_support import ssl_context
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional, Dict, Any, List

_SSL_CTX = ssl_context() if sys.platform == "darwin" else ssl._create_unverified_context()
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


# Match VPS resolve budget (130s) with safety margin so big photoshoots never cut off prematurely
RESOLVE_TIMEOUT = 150

class DownloadJob:
    def __init__(
        self,
        ps_input: str,
        save_dir: str,
        server_url: str,
        license_key: str,
        hwid: str,
        photo_threads: int = 6,
    ):
        self.ps_input = ps_input.strip()
        self.save_dir = Path(save_dir)
        server_clean = server_url.rstrip("/")
        if not server_clean.startswith("http://") and not server_clean.startswith("https://"):
            server_clean = f"http://{server_clean}"
        self.server_url = server_clean
        self.license_key = license_key.strip()
        self.hwid = hwid.strip()
        self.photo_threads = max(1, min(photo_threads, 32))

        # State
        self.id_str = ""
        self.uuid = ""
        self.title = ""
        self.folder_path = None
        self.total = 0
        self.downloaded = 0
        self.skipped = 0
        self.failed = 0
        self.done = 0
        self.status = "Queued"
        self.cancelled = False
        self.speed_str = "0.0 MB/s"

        # Metrics
        self._bytes_downloaded = 0
        self._start_time = 0.0

        # Callbacks
        self.on_progress = None
        self.on_log = None
        self.on_finished = None

    def cancel(self) -> None:
        self.cancelled = True
        self.status = "Cancelled"
        self._log(f"Job {self.title or self.ps_input} cancelled by user", "warn")
        if self.on_progress:
            self.on_progress(self)

    def _log(self, msg: str, tag: str = "info") -> None:
        if self.on_log:
            self.on_log(msg, tag)

    def _notify(self) -> None:
        if self.on_progress:
            self.on_progress(self)

    def _download_single_file(self, item: Dict[str, Any], dest: Path) -> str:
        """
        Downloads a single photo to dest path.
        Tries accelerated S3 URL first, then fallback URLs.
        Returns: 'ok', 'skip', 'fail', or 'cancel'.
        """
        if self.cancelled:
            return "cancel"

        # Skip if already exists and non-empty
        if dest.exists() and dest.stat().st_size > 0:
            self.skipped += 1
            self.done = self.downloaded + self.skipped + self.failed
            self._notify()
            return "skip"

        urls = item.get("urls", [])
        if not urls:
            self.failed += 1
            self.done = self.downloaded + self.skipped + self.failed
            self._log(f"  ❌ {dest.name} — No URL provided", "error")
            self._notify()
            return "fail"

        tmp_dest = dest.with_suffix(f"{dest.suffix}.part")

        last_error = ""
        for url in urls:
            if self.cancelled:
                return "cancel"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=25, context=_SSL_CTX) as resp:
                    with open(tmp_dest, "wb") as out_f:
                        while True:
                            if self.cancelled:
                                try: tmp_dest.unlink(missing_ok=True)
                                except Exception: pass
                                return "cancel"
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            out_f.write(chunk)
                            self._bytes_downloaded += len(chunk)

                # Rename atomically after full success
                tmp_dest.replace(dest)
                self.downloaded += 1
                self.done = self.downloaded + self.skipped + self.failed
                self._update_speed()
                self._notify()
                tag = f"[{self.uuid[:8]}] " if self.uuid else ""
                self._log(f"{tag}  ✅ {dest.name}", "success")
                return "ok"

            except Exception as e:
                last_error = str(e)
                try: tmp_dest.unlink(missing_ok=True)
                except Exception: pass
                continue
        # All mirrors failed
        self.failed += 1
        self.done = self.downloaded + self.skipped + self.failed
        self._log(f"  ❌ {dest.name} — Download failed: {last_error}", "error")
        self._notify()
        return "fail"

    def _update_speed(self) -> None:
        elapsed = time.time() - self._start_time
        if elapsed > 0.5:
            mb = self._bytes_downloaded / 1048576
            speed = mb / elapsed
            self.speed_str = f"{speed:.2f} MB/s"

    def run(self) -> None:
        if self.cancelled:
            return

        self.status = "Resolving…"
        self._notify()
        self._log(f"Resolving photoshoot with VPS: {self.ps_input}", "info")

        # 1. Resolve links securely via VPS Protected Engine
        resolve_api = f"{self.server_url}/api/photoshoot/resolve"
        payload = {
            "key": self.license_key,
            "hwid": self.hwid,
            "url": self.ps_input,
        }

        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                resolve_api,
                data=req_data,
                headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(req, timeout=RESOLVE_TIMEOUT, context=_SSL_CTX) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode("utf-8"))
                err_msg = err_data.get("error") or str(e)
            except Exception:
                err_msg = str(e)
            self.status = f"Error: {err_msg}"
            self._log(f"❌ Server rejected request: {err_msg}", "error")
            self._notify()
            if self.on_finished: self.on_finished(self)
            return
        except Exception as e:
            if "timed out" in str(e).lower():
                self.status = "Error: VPS timeout"
                self._log(f"❌ VPS did not answer within {RESOLVE_TIMEOUT}s. Please try again.", "error")
            else:
                self.status = "Error: Connection failed"
                self._log(f"❌ Cannot connect to VPS: {e}", "error")
            self._notify()
            if self.on_finished: self.on_finished(self)
            return

        if not result.get("success"):
            err_msg = result.get("error", "Unknown error from server")
            self.status = f"Error: {err_msg}"
            self._log(f"❌ Resolution failed: {err_msg}", "error")
            self._notify()
            if self.on_finished: self.on_finished(self)
            return

        # Setup folder & metadata
        self.uuid = result.get("uuid", "")
        self.title = result.get("title", "Photoshoot")
        folder_name = result.get("folder", self.title)
        items = result.get("items", [])
        self.total = len(items)

        if self.total == 0:
            self.status = "Done (0 photos)"
            self._log(f"No photos found in photoshoot '{self.title}'", "warn")
            self._notify()
            if self.on_finished: self.on_finished(self)
            return

        # Ensure output directory
        self.folder_path = self.save_dir / folder_name
        self.folder_path.mkdir(parents=True, exist_ok=True)
        tag = f"[{self.uuid[:8]}] " if self.uuid else ""
        ps_id_str = f" photoshootId={result.get('photoshoot_id', '')}" if result.get("photoshoot_id") else ""
        self._log(f"{tag}resolved address={self.title}{ps_id_str}", "success")
        self._log(f"{tag}Saving to: {self.folder_path}", "info")
        self._log(f"{tag}Found {self.total} photos", "info")
        self._log(f"{tag}Downloading…", "info")

        # 2. Concurrent high-speed download
        self.status = "Downloading…"
        self._start_time = time.time()
        self._notify()

        with ThreadPoolExecutor(max_workers=self.photo_threads) as executor:
            future_to_item = {
                executor.submit(
                    self._download_single_file,
                    item,
                    self.folder_path / re.sub(r'(?i)_replaced_camera', '', str(item.get("filename", "")))
                ): item
                for item in items
            }
            for fut in as_completed(future_to_item):
                if self.cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

        if self.cancelled:
            self.status = "Cancelled"
            self.speed_str = "0.0 MB/s"
        elif self.failed > 0:
            self.status = f"Done with {self.failed} errors"
            self._log(f"{tag}Finished: {self.downloaded}/{self.total} downloaded ({self.skipped} skipped, {self.failed} failed)", "warn")
        else:
            self.status = "✔ XONG [📂 MỞ]"
            self._log(f"{tag}Finished: {self.downloaded}/{self.total} downloaded", "success")

        self._notify()
        if self.on_finished:
            self.on_finished(self)
