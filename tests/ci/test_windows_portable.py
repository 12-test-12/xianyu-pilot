import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.ci import windows_portable as package


class PortablePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'XianyuPilot'
        for name in ['XianyuPilot.exe','_internal/web/index.html','_internal/web/assets/safety.js',
                     '_internal/app/desktop_migrations/006_full_console.sql','_internal/python311.dll',
                     '_internal/PySide6/QtWebEngineProcess.exe','_internal/PySide6/Qt6WebEngineCore.dll',
                     '_internal/PySide6/resources/qtwebengine_resources.pak','_internal/PySide6/resources/icudtl.dat',
                     '_internal/PySide6/translations/qtwebengine_locales/en-US.pak','_internal/vcruntime140.dll','_internal/msvcp140.dll']:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'test runtime')
        package.record(self.root,'a'*40)

    def test_package_checks_each_runtime_file_and_preserves_pending_acceptance(self):
        data=package.verify(self.root)
        self.assertFalse(data['realDeliveryEnabledByDefault'])
        self.assertIn('clean-vm',data['manualAcceptancePending'])
        output=package.package(self.root,Path(self.temp.name)/'release')
        with zipfile.ZipFile(output) as archive:
            self.assertIn('XianyuPilot/XianyuPilot.exe',archive.namelist())
            self.assertFalse(any('/data/' in name for name in archive.namelist()))
        self.assertIn(output.name,(output.parent/'SHA256SUMS.txt').read_text())

    def test_modified_or_missing_embedded_browser_cannot_pass(self):
        dll=self.root/'_internal/PySide6/Qt6WebEngineCore.dll'
        dll.write_bytes(b'changed')
        with self.assertRaises(ValueError):package.verify(self.root)
        dll.unlink()
        with self.assertRaises(ValueError):package.record(self.root,'a'*40)

    def rewrite_archive(self, output, change):
        with zipfile.ZipFile(output) as archive:
            files={name:archive.read(name) for name in archive.namelist()}
        change(files)
        with zipfile.ZipFile(output,'w') as archive:
            for name,data in files.items():
                archive.writestr(name,data)
        digest=hashlib.sha256(output.read_bytes()).hexdigest()
        (output.parent/'SHA256SUMS.txt').write_text(f'{digest}  {output.name}\n',encoding='utf-8')

    def test_release_runner_verifies_zip_without_extracting_or_installing_qt(self):
        output=package.package(self.root,Path(self.temp.name)/'release')
        archive,data=package.verify_archive(output.parent,'a'*40)
        self.assertEqual(archive,output)
        self.assertEqual(data['revision'],'a'*40)
        self.assertFalse((output.parent/'XianyuPilot').exists())

    def test_standalone_asset_is_bound_to_the_verified_build(self):
        standalone=Path(self.temp.name)/'standalone.exe'
        standalone.write_bytes(b'fixture standalone executable')
        output=package.package(self.root,Path(self.temp.name)/'release',standalone)
        archive,exe,data=package.verify_release(output.parent,'a'*40)
        self.assertEqual(exe.name,'XianyuPilot.exe')
        self.assertEqual(archive.name,'XianyuPilot-Windows-x64.zip')
        self.assertEqual(exe.read_bytes(),standalone.read_bytes())
        exe.write_bytes(b'changed executable')
        with self.assertRaises(ValueError):package.verify_release(output.parent,'a'*40)
        package.package(self.root,output.parent,standalone)
        build_info=output.parent/'windows-build-info.json'
        value=json.loads(build_info.read_text());value['revision']='b'*40
        build_info.write_text(json.dumps(value))
        with self.assertRaises(ValueError):package.verify_release(output.parent,'a'*40)

    def test_release_rejects_changed_zip_checksum_or_inner_file(self):
        output=package.package(self.root,Path(self.temp.name)/'release')
        output.write_bytes(output.read_bytes()+b'changed')
        with self.assertRaises(ValueError):package.verify_archive(output.parent,'a'*40)
        output=package.package(self.root,output.parent)
        self.rewrite_archive(output,lambda files:files.update({'XianyuPilot/XianyuPilot.exe':b'changed'}))
        with self.assertRaises(ValueError):package.verify_archive(output.parent,'a'*40)

    def test_release_rejects_a_manifest_for_another_commit(self):
        output=package.package(self.root,Path(self.temp.name)/'release')
        def change(files):
            name='XianyuPilot/'+package.MANIFEST
            manifest=json.loads(files[name])
            manifest['revision']='b'*40
            files[name]=json.dumps(manifest).encode()
        self.rewrite_archive(output,change)
        with self.assertRaises(ValueError):package.verify_archive(output.parent,'a'*40)

    def test_release_rejects_private_extra_traversal_and_duplicate_zip_paths(self):
        for name in ('XianyuPilot/data/private','../escape','XianyuPilot/extra','XianyuPilot/xianyupilot.exe'):
            with self.subTest(name=name):
                output=package.package(self.root,Path(self.temp.name)/'release')
                self.rewrite_archive(output,lambda files:files.update({name:b'unexpected'}))
                with self.assertRaises(ValueError):package.verify_archive(output.parent,'a'*40)

    def test_runtime_data_and_private_settings_cannot_enter_distribution(self):
        for name in ['data/app.sqlite3','.env','.env.production','secrets/token']:
            path=self.root/name;path.parent.mkdir(exist_ok=True);path.write_bytes(b'private')
            with self.assertRaises(ValueError):package.record(self.root,'a'*40)
            path.unlink()

    def test_invalid_revision_and_changed_manifest_are_rejected(self):
        with self.assertRaises(ValueError):package.record(self.root,'main')
        path=self.root/package.MANIFEST
        data=json.loads(path.read_text());data['distribution']='onefile';path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):package.verify(self.root)

    def test_build_is_onedir_and_ci_downloads_tools_and_checks_frozen_outputs(self):
        root=Path(__file__).resolve().parents[2]
        spec=(root/'packaging/windows/xianyu_portable.spec').read_text()
        workflow=(root/'.github/workflows/ci-checks.yml').read_text()
        self.assertIn('exclude_binaries=True',spec)
        self.assertIn('COLLECT(',spec)
        self.assertIn('windows-portable:',workflow)
        self.assertIn('packaging/windows/requirements-build.txt',workflow)
        self.assertIn('windows_portable_smoke.py',workflow)
        self.assertNotIn('--onefile',spec)
