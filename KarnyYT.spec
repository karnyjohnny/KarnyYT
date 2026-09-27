# -*- mode: python ; coding: utf-8 -*-
"""
KarnyYT.spec - jedna analiza, dwie binarki:
  * dist/KarnyYT/KarnyYT.exe          (onedir - zalecany na co dzień:
                                       szybszy start, mniej false-positive AV)
  * dist/KarnyYT-onefile.exe          (onefile - "wrzuć i działaj",
                                       rozpakowuje się do %TEMP% przy starcie)

Build:  pyinstaller --noconfirm --clean KarnyYT.spec
"""

block_cipher = None

datas = [
    ("assets/icon.ico", "assets"),
    ("cookies.example.json", "."),
]

# Nie importujemy tych modułów PyQt5 - wycinamy je, żeby binarka była
# mniejsza i nie ciągnęła nieużywanych DLL-i Qt.
excludes = [
    "tkinter",
    "unittest",
    "pydoc_data",
    "PyQt5.QtQml",
    "PyQt5.QtQuick",
    "PyQt5.QtQuickWidgets",
    "PyQt5.QtWebEngine",
    "PyQt5.QtWebEngineCore",
    "PyQt5.QtWebEngineWidgets",
    "PyQt5.QtWebSockets",
    "PyQt5.QtNetwork",
    "PyQt5.QtBluetooth",
    "PyQt5.QtNfc",
    "PyQt5.QtPositioning",
    "PyQt5.QtSensors",
    "PyQt5.QtSerialPort",
    "PyQt5.QtMultimedia",
    "PyQt5.QtMultimediaWidgets",
    "PyQt5.QtSql",
    "PyQt5.QtTest",
    "PyQt5.QtXml",
    "PyQt5.QtXmlPatterns",
    "PyQt5.Qt3DCore",
    "PyQt5.Qt3DRender",
    "PyQt5.QtCharts",
    "PyQt5.QtDataVisualization",
    "PyQt5.QtOpenGL",
]

a = Analysis(
    ["KarnyYT.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["karnyyt"],
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# --- onedir -------------------------------------------------------------------
exe_dir = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KarnyYT",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe_dir,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="KarnyYT",
)

# --- onefile --------------------------------------------------------------------
exe_one = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="KarnyYT-onefile",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/icon.ico",
)
