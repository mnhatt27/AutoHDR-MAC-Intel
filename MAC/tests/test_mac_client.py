from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import queue
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "client_source"))
import app
import downloader
import hwid
import mac_updates
import platform_support


class Response(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.headers = {"Content-Length": str(len(content))}


def update_zip():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("AutoHDR.app/Contents/Info.plist", "<plist/>")
    return stream.getvalue()


class PlatformTests(unittest.TestCase):
    def test_configuration_is_outside_app_bundle(self):
        with patch.object(platform_support, "IS_MAC", True), patch.object(Path, "home", return_value=Path("/Users/Test")):
            self.assertEqual(
                platform_support.config_path(Path("/Applications/AutoHDR.app/Contents/MacOS")),
                Path("/Users/Test/Library/Application Support/AutoHDR/photoshoot_config.json"),
            )

    def test_windows_config_keeps_existing_location(self):
        with patch.object(platform_support, "IS_MAC", False):
            self.assertEqual(platform_support.config_path(Path("client")), Path("client/photoshoot_config.json"))

    def test_mac_hwid_survives_os_hostname_and_architecture_changes(self):
        output = '"IOPlatformUUID" = "12345678-1234-4321-ABCD-123456789012"'
        with patch.object(hwid.platform, "system", return_value="Darwin"), patch.object(hwid.subprocess, "check_output", return_value=output):
            with patch.object(hwid.platform, "machine", return_value="arm64"), patch.object(hwid.platform, "release", return_value="24.0"), patch.object(hwid.platform, "node", return_value="old"):
                native = hwid.get_hwid()
            with patch.object(hwid.platform, "machine", return_value="x86_64"), patch.object(hwid.platform, "release", return_value="25.1"), patch.object(hwid.platform, "node", return_value="renamed"):
                rosetta = hwid.get_hwid()
            self.assertEqual(native, rosetta)
            self.assertEqual(len(native), 64)

    def test_mac_hwid_rejects_missing_and_zero_uuid(self):
        with patch.object(hwid.platform, "system", return_value="Darwin"):
            for output in ("", '"IOPlatformUUID" = "00000000-0000-0000-0000-000000000000"'):
                with patch.object(hwid.subprocess, "check_output", return_value=output), self.assertRaises(RuntimeError):
                    hwid.get_hwid()

    def test_finder_receives_path_as_single_argument(self):
        with patch.object(platform_support, "IS_MAC", True), patch.object(platform_support.subprocess, "Popen") as launch:
            folder = Path(tempfile.gettempdir()) / "Photos with spaces ' and quotes"
            platform_support.open_folder(folder)
            launch.assert_called_once_with(["/usr/bin/open", str(folder.resolve())], close_fds=True)

    def test_binary_architecture_selects_update(self):
        for machine, expected in (("arm64", "arm64"), ("x86_64", "x86_64")):
            with patch.object(platform_support.platform, "machine", return_value=machine):
                self.assertEqual(platform_support.mac_arch(), expected)


class UpdateTests(unittest.TestCase):
    def test_windows_manifest_is_not_used_on_mac(self):
        self.assertIsNone(mac_updates.select_release({"latest_version": "99", "download_url": "/windows.exe"}, "arm64"))

    def test_update_requires_matching_arch_and_checksum(self):
        release = {"latest_version": "2.0.2", "download_url": "/arm.zip", "sha256": "a" * 64}
        info = {"macos": {"arm64": release}}
        self.assertEqual(mac_updates.select_release(info, "arm64"), release)
        self.assertIsNone(mac_updates.select_release(info, "x86_64"))
        release["sha256"] = "invalid"
        self.assertIsNone(mac_updates.select_release(info, "arm64"))

    def test_verified_zip_download(self):
        content = update_zip()
        release = {"download_url": "/mac.zip", "sha256": hashlib.sha256(content).hexdigest()}
        with tempfile.TemporaryDirectory() as directory, patch.object(mac_updates, "urlopen", return_value=Response(content)) as request:
            progress = []
            result = mac_updates.download_release("https://example.test", release, Path(directory), lambda n, total: progress.append((n, total)))
            self.assertEqual(result.read_bytes(), content)
            self.assertEqual(progress[-1], (len(content), len(content)))
            self.assertEqual(request.call_args.args[0].full_url, "https://example.test/mac.zip")
            self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_checksum_mismatch_discards_download(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(mac_updates, "urlopen", return_value=Response(update_zip())):
            with self.assertRaisesRegex(ValueError, "checksum"):
                mac_updates.download_release("https://example.test", {"download_url": "/mac.zip", "sha256": "0" * 64}, Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_exe_cannot_be_installed_even_with_matching_checksum(self):
        content = b"MZ Windows executable"
        with tempfile.TemporaryDirectory() as directory, patch.object(mac_updates, "urlopen", return_value=Response(content)):
            with self.assertRaises(zipfile.BadZipFile):
                mac_updates.download_release("https://example.test", {"download_url": "/app", "sha256": hashlib.sha256(content).hexdigest()}, Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])


class ClientTests(unittest.TestCase):
    def test_worker_ui_dispatch_does_not_touch_tk(self):
        application = app.PhotoshootApp.__new__(app.PhotoshootApp)
        application._ui_queue = queue.Queue()
        results = []
        application.call_on_ui(lambda: results.append("main thread"))
        self.assertEqual(results, [])
        application._ui_queue.get_nowait()()
        self.assertEqual(results, ["main thread"])

    def test_resolve_to_download_pipeline_and_filename_cleanup(self):
        result = {"success": True, "title": "Test", "folder": "Test", "items": [{"filename": "photo_replaced_camera.jpg", "urls": ["https://example.test/photo"]}]}
        def respond(request, **kwargs):
            return Response(json.dumps(result).encode() if request.full_url.endswith("/resolve") else b"photo data")
        with tempfile.TemporaryDirectory() as directory, patch.object(downloader.urllib.request, "urlopen", side_effect=respond):
            job = downloader.DownloadJob("test", directory, "https://example.test", "test-key", "test-hwid")
            job.run()
            self.assertEqual((Path(directory) / "Test" / "photo.jpg").read_bytes(), b"photo data")
            self.assertEqual((job.downloaded, job.failed), (1, 0))
            self.assertIn("XONG", job.status)

    def test_full_ui_with_mac_buttons_and_frozen_controls(self):
        # Runs on both Windows locally and native macOS CI, without real license use.
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "CONFIG_FILE", Path(directory) / "config.json"), patch.object(app, "get_hwid", return_value="test-hwid"), patch.object(app, "BUTTON_CLASS", platform_support.MacButton):
            application = app.PhotoshootApp(startup_checks=False)
            try:
                application.root.update_idletasks()
                application._set_ui_frozen(False)
                self.assertEqual(str(application.add_btn["state"]), "normal")
                application._set_ui_frozen(True)
                self.assertEqual(str(application.add_btn["state"]), "disabled")
                application._autosave_config()
                self.assertTrue((Path(directory) / "config.json").is_file())
            finally:
                application.root.destroy()


if __name__ == "__main__":
    unittest.main()
