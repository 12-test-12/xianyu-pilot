# -*- mode: python ; coding: utf-8 -*-
# Publish both a complete directory ZIP and a self-contained EXE.
from pathlib import Path
import os
import subprocess
from PyInstaller.utils.hooks import collect_all, copy_metadata
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
# Compile in the build environment so the portable app needs no runtime compiler privileges.
qq_source=root/'apps/api/app/resources/qq_draft.cs'
qq_helper=Path(workpath)/'qq_draft.dll'
csc=Path(os.environ['SystemRoot'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
subprocess.run([str(csc),'/nologo','/target:library',f'/out:{qq_helper}',str(qq_source)],check=True)
# Include the Playwright Node driver in frozen builds.
# QR login uses installed Chrome/Edge, then Playwright Chromium as fallback.
playwright_datas,playwright_binaries,playwright_hidden=collect_all('playwright')
a=Analysis(
    [str(root/'apps/api/run_portable.py')],pathex=[str(root/'apps/api')],
    binaries=[*playwright_binaries],datas=[(str(web),'web'),(str(root/'apps/api/app/desktop_migrations'),'app/desktop_migrations'),
        (str(root/'apps/api/app/data/categories.json'),'app/resources'),
        (str(root/'apps/api/app/data/china_address_dict.json'),'app/resources'),
        (str(root/'apps/api/app/resources/qiuqiu-assist.zip'),'app/resources'),
        (str(root/'apps/api/app/resources/qq_draft.ps1'),'app/resources'),
        (str(qq_helper),'app/resources'),
        *project_notices,*playwright_datas]+copy_metadata('PySide6',recursive=True),
    hiddenimports=['app.portable.qt_host','app.portable.webengine_check','sqlalchemy.dialects.sqlite.aiosqlite',
        'aiosqlite','uvicorn.protocols.http.h11_impl','uvicorn.lifespan.on','uvicorn.loops.asyncio',
        'uvicorn.protocols.websockets.websockets_impl',*playwright_hidden],
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
    # Keep live DLLs, certificates and web assets out of Windows' shared Temp folder.
    runtime_tmpdir=r'%LOCALAPPDATA%\XianyuPilot\Runtime',
    disable_windowed_traceback=True)
