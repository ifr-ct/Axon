# Windows x64 single-file build; pywebview/pythonnet ship their own PyInstaller hooks.
from pathlib import Path

root = Path(SPECPATH)
analysis = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'web'), 'web')],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=['webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cocoa',
              'webview.platforms.android', 'webview.platforms.cef'],
    noarchive=False,
)
archive = PYZ(analysis.pure)
exe = EXE(
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name='TelemetryStudio',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
