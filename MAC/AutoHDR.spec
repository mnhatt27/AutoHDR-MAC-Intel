# PyInstaller executes this file; SPECPATH is the directory of this specification.
import ast
import os
from pathlib import Path

root = Path(SPECPATH).parent
source = root / "client_source"
tree = ast.parse((source / "app.py").read_text(encoding="utf-8"))
version = next(ast.literal_eval(node.value) for node in tree.body
               if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "APP_VERSION" for t in node.targets))
arch = os.environ["AUTOHDR_TARGET_ARCH"]

a = Analysis(
    [str(root / "MAC" / "launcher.py")],
    pathex=[str(source)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="AutoHDR",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, target_arch=arch, codesign_identity=None, entitlements_file=None,
)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="AutoHDR")
app = BUNDLE(
    collection, name="AutoHDR.app", icon=None,
    bundle_identifier="com.mystic.autohdr.download",
    version=version,
    info_plist={
        "CFBundleDisplayName": "AutoHDR Download",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "NSHumanReadableCopyright": "AutoHDR Download - Remake By Mystic",
    },
)
