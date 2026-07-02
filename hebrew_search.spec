# -*- mode: python ; coding: utf-8 -*-
"""מפרט אריזה ל-PyInstaller עבור תוכנת החיפוש בעברית.

אורז לקובץ EXE יחיד ועצמאי: קוד Python, ה-frontend הבנוי, מודלי השפה של
Tesseract, ומנוע Tesseract המלא - כך שה-OCR עובד ללא התקנה חיצונית.
"""

import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas = []
binaries = []
hiddenimports = []

# איסוף מלא של חבילות עם משאבים/תוספים דינמיים
for pkg in [
    "webview",
    "clr_loader",
    "pythonnet",
    "uvicorn",
    "pydantic",
    "pydantic_core",
    "pypdfium2",
    "pypdfium2_raw",
    "pdfplumber",
    "pdfminer",
    "charset_normalizer",
    "anyio",
    "tantivy",
]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

datas += collect_data_files("docx")

for pkg in ["uvicorn", "fastapi", "starlette", "pytesseract", "PIL"]:
    hiddenimports += collect_submodules(pkg)

hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

# משאבי האפליקציה: frontend בנוי + מודלי שפה
datas += [
    ("frontend/dist", "frontend/dist"),
    ("tessdata", "tessdata"),
]

# מנוע Tesseract המלא (עצמאי) - אם מותקן במחשב הבנייה
_tess_dir = r"C:\Program Files\Tesseract-OCR"
if os.path.isdir(_tess_dir):
    datas += [(_tess_dir, "tesseract")]

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy.tests"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="HebrewSearch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon="build_assets/app.ico" if os.path.exists("build_assets/app.ico") else None,
)
