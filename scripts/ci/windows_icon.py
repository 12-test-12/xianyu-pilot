"""Verify the Explorer icon embedded in the EXEs that GitHub will distribute."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ICON = ROOT / 'apps/web/public/favicon.ico'
SIZES = (16, 24, 32, 48, 64, 128, 256)


def icon_frames(data: bytes) -> dict:
    if len(data) < 6 + 16 * len(SIZES) or struct.unpack_from('<HHH', data) != (0, 1, len(SIZES)):
        raise ValueError('Brand ICO must contain all seven Windows icon sizes')
    frames = {}
    end = 6 + 16 * len(SIZES)
    for index in range(len(SIZES)):
        width, height, colors, reserved, planes, bits, length, offset = struct.unpack_from(
            '<BBBBHHII', data, 6 + 16 * index)
        size = width or 256
        if size != (height or 256) or size not in SIZES or size in frames or reserved != 0 \
                or length == 0 or offset < end or offset + length > len(data):
            raise ValueError('Brand ICO has invalid, missing or overlapping frames')
        frames[size] = ((width, height, colors, reserved, planes, bits), data[offset:offset + length])
        end = offset + length
    return frames


def resource_variants(pe, entry) -> dict:
    result = {}
    for language in entry.directory.entries:
        location = language.data.struct
        content = pe.get_data(location.OffsetToData, location.Size)
        if language.id in result or len(content) != location.Size or not content:
            raise ValueError('Invalid icon resource language or length')
        result[language.id] = content
    if not result:
        raise ValueError('Empty icon resource')
    return result


def verify_executable(data: bytes, frames: dict, label: str) -> dict:
    """Compare RT_GROUP_ICON and RT_ICON bytes, without running Windows or the EXE."""
    import pefile

    try:
        with pefile.PE(data=data, fast_load=True) as pe:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
            types = {entry.id: entry for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries}
            icons = {entry.id: resource_variants(pe, entry) for entry in types[3].directory.entries}
            groups = types[14].directory.entries
            if not groups:
                raise ValueError('No Explorer icon group')
            count = 0
            # Check every group/language: a matching secondary icon cannot hide a wrong default icon.
            for group in groups:
                for language, content in resource_variants(pe, group).items():
                    if len(content) != 6 + 14 * len(frames) or struct.unpack_from('<HHH', content) != (0, 1, len(frames)):
                        raise ValueError('Embedded icon does not contain all seven sizes')
                    found = set()
                    for index in range(len(frames)):
                        *metadata, length, identity = struct.unpack_from('<BBBBHHIH', content, 6 + 14 * index)
                        size = metadata[0] or 256
                        if size in found or size not in frames:
                            raise ValueError('Embedded icon has duplicate or unexpected sizes')
                        expected_metadata, expected_content = frames[size]
                        variants = icons[identity]
                        actual = variants.get(language, variants.get(0))
                        if tuple(metadata) != expected_metadata or length != len(expected_content) or actual != expected_content:
                            raise ValueError(f'Embedded {size}px icon differs from the committed Gemini icon')
                        found.add(size)
                    count += 1
    except (pefile.PEFormatError, AttributeError, KeyError, IndexError, struct.error, ValueError) as error:
        raise ValueError(f'{label}: invalid or incorrect embedded app icon ({error})') from error
    return {'file': label, 'sha256': hashlib.sha256(data).hexdigest(), 'iconGroups': count, 'sizes': list(SIZES)}


def verify_release(directory: Path, icon: Path = SOURCE_ICON) -> dict:
    """Recheck the exact standalone attachment and the executable inside the download ZIP."""
    source = icon.read_bytes()
    frames = icon_frames(source)
    executable = directory / 'XianyuPilot.exe'
    archive = directory / 'XianyuPilot-Windows-x64.zip'
    results = [verify_executable(executable.read_bytes(), frames, executable.name)]
    with zipfile.ZipFile(archive) as bundle:
        entry = 'XianyuPilot/XianyuPilot.exe'
        if bundle.namelist().count(entry) != 1:
            raise ValueError('Download ZIP must contain exactly one main executable')
        results.append(verify_executable(bundle.read(entry), frames, archive.name + '/' + entry))
        if bundle.read('XianyuPilot/_internal/web/favicon.ico') != source:
            raise ValueError('Download ZIP contains a stale Web/window icon')
    return {'iconSha256': hashlib.sha256(source).hexdigest(), 'verified': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--icon', type=Path, default=SOURCE_ICON)
    parser.add_argument('--web-icon', type=Path)
    parser.add_argument('--exe', type=Path, action='append', default=[])
    parser.add_argument('--release-directory', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if not (args.web_icon or args.exe or args.release_directory):
        parser.error('Specify a Web icon, executable or release directory to verify')
    source = args.icon.read_bytes()
    frames = icon_frames(source)
    report = {'iconSha256': hashlib.sha256(source).hexdigest(), 'verified': []}
    if args.web_icon:
        if args.web_icon.read_bytes() != source:
            raise ValueError('Built Web icon differs from the committed Gemini icon; rebuild the frontend')
        report['webIcon'] = str(args.web_icon)
    for executable in args.exe:
        report['verified'].append(verify_executable(executable.read_bytes(), frames, str(executable)))
    if args.release_directory:
        report['verified'].extend(verify_release(args.release_directory, args.icon)['verified'])
    content = json.dumps(report, indent=2) + '\n'
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(content, encoding='utf-8')
    print(content, end='')


if __name__ == '__main__':
    main()
