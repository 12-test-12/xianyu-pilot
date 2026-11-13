"""Probe EXE from unrelated cwd, then move the entire isolated test copy."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def run(bundle,workspace,*,webengine=True,standalone=None):
    workspace=workspace.resolve()
    workspace.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='portable-smoke-',dir=workspace) as temporary:
        root=Path(temporary)
        first=root/'中文 portable A'/'XianyuPilot'
        second=root/'移动盘符模拟 B'/'XianyuPilot'
        outside=root/'unrelated-cwd';outside.mkdir()
        forbidden=root/'inherited-user-and-temp';forbidden.mkdir()
        local_app_data=root/'isolated-local-appdata';local_app_data.mkdir()
        runtime_dir=local_app_data/'XianyuPilot/Runtime'
        env=dict(os.environ)
        env.update({'PATH':str(Path(os.environ['SystemRoot'])/'System32'),'APPDATA':str(forbidden),
                    'LOCALAPPDATA':str(local_app_data),'TEMP':str(forbidden),'TMP':str(forbidden)})
        for key in ('PYTHONHOME','PYTHONPATH','QTWEBENGINE_CHROMIUM_FLAGS','QTWEBENGINE_REMOTE_DEBUGGING'):
            env.pop(key,None)
        if standalone is not None:
            first.mkdir(parents=True)
            shutil.copy2(standalone,first/'XianyuPilot.exe')
        else:
            shutil.copytree(bundle,first)
        def probe(folder,flag):
            def diagnostics():
                destination=Path('reports/windows-portable-diagnostics')/('standalone' if standalone else 'directory')
                destination.mkdir(parents=True,exist_ok=True)
                for name in ('portable-self-check.json','webengine-check.json','webengine-check.png','desktop.log'):
                    source=folder/'data/logs'/name
                    if source.is_file():shutil.copy2(source,destination/name)
                report=folder/'data/logs/webengine-check.json'
                if report.is_file():print(report.read_text(encoding='utf-8'),flush=True)
            try:
                result=subprocess.run([str(folder/'XianyuPilot.exe'),flag,'--port','19177'],cwd=outside,env=env,timeout=90,check=False)
            except subprocess.TimeoutExpired:
                diagnostics()
                raise
            if result.returncode:
                diagnostics()
                raise RuntimeError(f'Frozen {flag} failed: {result.returncode}')
        def self_check(folder):
            probe(folder,'--self-check')
            report=json.loads((folder/'data/logs/portable-self-check.json').read_text(encoding='utf-8'))
            data_root=Path(report['dataRoot']).resolve()
            if not report['frozen'] or data_root!=(folder/'data').resolve():
                raise ValueError('frozen data root escaped')
            bundle_root=Path(report['bundleRoot']).resolve()
            if standalone is not None:
                if bundle_root.parent!=runtime_dir.resolve() or not bundle_root.name.startswith('_MEI'):
                    raise ValueError('standalone bundle must extract under LocalAppData/XianyuPilot/Runtime')
            elif bundle_root!=(folder/'_internal').resolve():
                raise ValueError('directory bundle must use its packaged _internal folder')
            return report
        before=self_check(first)
        second.parent.mkdir()
        # Both checked absolute paths are inside this disposable test workspace.
        if not first.resolve().is_relative_to(root) or not second.resolve().is_relative_to(root):
            raise ValueError('unsafe relocation target')
        shutil.move(str(first),str(second))
        after=self_check(second)
        if after['storageToken']!=before['storageToken']:
            raise ValueError('portable relocation lost database identity')
        if webengine:
            probe(second,'--webengine-check')
            ui=json.loads((second/'data/logs/webengine-check.json').read_text(encoding='utf-8'))
            if not ui['ok'] or not ui.get('originalConsoleRendered'):
                raise ValueError('embedded Chromium did not render Vue')
        if list(outside.iterdir()):
            raise ValueError('application wrote data relative to the calling cwd')
        if list(forbidden.iterdir()):
            raise ValueError('application left files in inherited AppData or Temp directories')
        if standalone is not None and runtime_dir.is_dir() and any(runtime_dir.iterdir()):
            raise ValueError('standalone bundle left extracted files after exit')
        return {'frozenStartup':True,'externalCwd':True,'relocatedDatabase':True,'embeddedVueRendered':webengine,'standalone':standalone is not None,
                'inheritedUserTempUntouched':True,'developerPathRemoved':True,
                'nativeTrayValidated':False,'cleanVmValidated':False,'crossVolumeValidated':False,'fullIoIsolationValidated':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--directory',type=Path)
    source.add_argument('--standalone-exe',type=Path)
    parser.add_argument('--workspace',type=Path,default=Path('.tmp/portable-validation'))
    parser.add_argument('--report',type=Path,default=Path('reports/windows-portable-smoke.json'))
    args=parser.parse_args()
    result=run(args.directory.resolve() if args.directory else None,args.workspace,standalone=args.standalone_exe.resolve() if args.standalone_exe else None)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2),encoding='utf-8')
