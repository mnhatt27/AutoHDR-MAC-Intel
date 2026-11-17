"""
Hardware Identification (HWID) Fingerprint Generator
Generates a unique, stable hardware hash for machine-binding license validation.
"""
from __future__ import annotations
import os
import platform
import hashlib
import subprocess
import re

def get_hwid() -> str:
    """
    Computes a stable SHA-256 machine fingerprint.
    Combines motherboard/OS UUID, machine architecture, and system info.
    """
    if platform.system() == "Darwin":
        # IOPlatformUUID is independent of OS updates, hostname, account name,
        # and whether this binary is native ARM or running under Rosetta.
        output = subprocess.check_output(
            ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            text=True, timeout=10,
        )
        match = re.search(r'"IOPlatformUUID"\s*=\s*"([0-9A-Fa-f-]{36})"', output)
        if not match or match.group(1).replace("-", "") == "0" * 32:
            raise RuntimeError("Cannot read the Mac hardware UUID for license validation")
        return hashlib.sha256(("AutoHDR|macOS|" + match.group(1).upper()).encode("utf-8")).hexdigest()

    elements = []

    # 1. Windows MachineGuid from Registry (Fastest and most reliable)
    if platform.system() == "Windows":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                if guid:
                    elements.append(str(guid).strip())
        except Exception:
            pass

    # 2. Windows WMI / CIM ComputerSystemProduct UUID fallback
    if platform.system() == "Windows" and len(elements) == 0:
        try:
            cmd = 'powershell -Command "(Get-CimInstance -Class Win32_ComputerSystemProduct).UUID"'
            out = subprocess.check_output(cmd, shell=True, text=True).strip()
            if out:
                elements.append(out)
        except Exception:
            pass

    # 3. Hardware & OS traits
    elements.extend([
        platform.system(),
        platform.release(),
        platform.machine(),
        platform.node(),
        os.environ.get("PROCESSOR_IDENTIFIER", ""),
        os.environ.get("USERNAME", ""),
    ])

    raw = "|".join(elements)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

if __name__ == "__main__":
    print("Machine HWID:", get_hwid())
