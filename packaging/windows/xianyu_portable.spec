# -*- mode: python ; coding: utf-8 -*-
# Publish both a complete directory ZIP and a self-contained EXE.
from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata
root=Path(SPECPATH).resolve().parents[1]
web=root/'apps/web/dist'
if not (web/'index.html').is_file():
    raise SystemExit('Build the original Vue project before packaging')
icon=root/'apps/web/public/favicon.ico'
if not icon.is_file() or (web/'favicon.ico').read_bytes()!=icon.read_bytes():
    raise SystemExit('Rebuild the frontend with the committed Gemini icon before packaging')
project_notices=[(str(root/'LICENSE'),'licenses/project')]
if (root/'NOTICE').is_file():
    project_notices.append((str(root/'NOTICE'),'licenses/project'))
a=Analysis(
    [str(root/'apps/api/run_portable.py')],pathex=[str(root/'apps/api')],
    binaries=[],datas=[(str(web),'web'),(str(root/'apps/api/app/desktop_migrations'),'app/desktop_migrations'),
        (str(root/'apps/api/app/data/china_address_dict.json'),'app/resources'),
        *project_notices]+copy_metadata('PySide6',recursive=True),
    hiddenimports=['app.portable.qt_host','app.portable.webengine_check','sqlalchemy.dialects.sqlite.aiosqlite',
        'aiosqlite','uvicorn.protocols.http.h11_impl','uvicorn.lifespan.on','uvicorn.loops.asyncio',
        'uvicorn.protocols.websockets.websockets_impl'],
    hookspath=[],runtime_hooks=[str(root/'packaging/windows/portable_runtime_hook.py')],
    excludes=['PyQt5','PyQt6','PySide2','tkinter','pytest','IPython','matplotlib','numpy','pandas'],
    noarchive=False,
)
# Qt uses Windows' unversioned ICU API. A developer PATH can contain Poppler's
# identically named ICU DLL with versioned exports; bundling it shadows the OS
# library and makes QtCore fail to import on a clean launch.
a.binaries=[entry for entry in a.binaries
            if Path(entry[0]).name.casefold() not in {'icu.dll','icuin.dll','icuuc.dll'}]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='XianyuPilot',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False,icon=str(icon),
    disable_windowed_traceback=True,contents_directory='_internal')
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='XianyuPilot')
standalone=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='XianyuPilot-Standalone',debug=False,
    bootloader_ignore_signals=False,strip=False,upx=False,console=False,icon=str(icon),
    disable_windowed_traceback=True)
