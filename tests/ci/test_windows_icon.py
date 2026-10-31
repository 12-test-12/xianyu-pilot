from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

from scripts.ci import windows_icon
from windows_icon_fixture import executable


class WindowsIconTests(unittest.TestCase):
    def setUp(self):
        self.icon = windows_icon.SOURCE_ICON.read_bytes()
        self.frames = windows_icon.icon_frames(self.icon)

    def test_real_pe_resources_match_every_size_and_language(self):
        result = windows_icon.verify_executable(executable(self.frames, languages=(0, 1033)), self.frames, 'app.exe')
        self.assertEqual(result['sizes'], [16, 24, 32, 48, 64, 128, 256])
        self.assertEqual(result['iconGroups'], 2)

    def test_generic_missing_wrong_and_incomplete_icons_are_rejected(self):
        wrong = dict(self.frames)
        metadata, content = wrong[16]
        wrong[16] = metadata, b'wrong icon' + content[10:]
        incomplete = dict(self.frames)
        del incomplete[32]
        for payload in (b'not a PE', executable(wrong), executable(incomplete),
                        executable(self.frames, wrong_default=True)):
            with self.subTest(payload_length=len(payload)), self.assertRaisesRegex(ValueError, 'app.exe'):
                windows_icon.verify_executable(payload, self.frames, 'app.exe')

    def test_malformed_brand_ico_cannot_be_used_as_reference(self):
        overlap = bytearray(self.icon)
        struct.pack_into('<I', overlap, 18, 6)
        missing_size = bytearray(self.icon)
        missing_size[6] = 20
        for payload in (b'no icon', self.icon[:100], bytes(overlap), bytes(missing_size)):
            with self.assertRaises(ValueError):
                windows_icon.icon_frames(payload)

    def test_actual_download_zip_and_standalone_are_checked_independently(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            standalone = root / 'XianyuPilot.exe'
            archive = root / 'XianyuPilot-Windows-x64.zip'
            good = executable(self.frames)
            standalone.write_bytes(good)

            def write_zip(payload, icon=self.icon):
                with zipfile.ZipFile(archive, 'w') as bundle:
                    bundle.writestr('XianyuPilot/XianyuPilot.exe', payload)
                    bundle.writestr('XianyuPilot/_internal/web/favicon.ico', icon)

            write_zip(good)
            self.assertEqual(len(windows_icon.verify_release(root)['verified']), 2)
            write_zip(b'old executable')
            with self.assertRaises(ValueError):
                windows_icon.verify_release(root)
            write_zip(good, b'old window icon')
            with self.assertRaises(ValueError):
                windows_icon.verify_release(root)
            write_zip(good)
            standalone.write_bytes(b'old standalone executable')
            with self.assertRaises(ValueError):
                windows_icon.verify_release(root)

    def test_stale_frontend_icon_fails_before_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            icon = Path(temporary) / 'favicon.ico'
            icon.write_bytes(b'old icon')
            result = subprocess.run([sys.executable, str(windows_icon.ROOT / 'scripts/ci/windows_icon.py'),
                                     '--web-icon', str(icon)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('rebuild the frontend', result.stderr)


if __name__ == '__main__':
    unittest.main()
