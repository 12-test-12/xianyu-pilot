"""Minimal PE with real resource directories; never executed by tests."""
import struct


def executable(frames, *, wrong_default=False, languages=(0,)):
    icons = {}
    group = bytearray(struct.pack('<HHH', 0, 1, len(frames)))
    for identity, (metadata, content) in enumerate(frames.values(), 1):
        icons[identity] = {language: content for language in languages}
        group.extend(struct.pack('<BBBBHHIH', *metadata, len(content), identity))
    groups = {2: {language: bytes(group) for language in languages}}
    if wrong_default:
        # The default group is generic although a matching brand icon exists second.
        groups[1] = {0: struct.pack('<HHH', 0, 1, 0)}
    resources = bytearray()

    def allocate(length):
        resources.extend(b'\0' * (-len(resources) % 4))
        offset = len(resources)
        resources.extend(b'\0' * length)
        return offset

    def directory(entries):
        offset = allocate(16 + 8 * len(entries))
        struct.pack_into('<IIHHHH', resources, offset, 0, 0, 0, 0, 0, len(entries))
        for index, (identity, value) in enumerate(sorted(entries.items())):
            if isinstance(value, dict):
                target = directory(value) | 0x80000000
            else:
                target = allocate(16)
                content = allocate(len(value))
                resources[content:content + len(value)] = value
                struct.pack_into('<IIII', resources, target, 0x1000 + content, len(value), 0, 0)
            struct.pack_into('<II', resources, offset + 16 + 8 * index, identity, target)
        return offset

    directory({3: icons, 14: groups})
    headers = bytearray(0x200)
    headers[:2] = b'MZ'
    struct.pack_into('<I', headers, 0x3c, 0x80)
    headers[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', headers, 0x84, 0x8664, 1, 0, 0, 0, 240, 0x22)
    optional = 0x98
    struct.pack_into('<H', headers, optional, 0x20b)
    struct.pack_into('<Q', headers, optional + 24, 0x140000000)
    struct.pack_into('<II', headers, optional + 32, 0x1000, 0x200)
    struct.pack_into('<II', headers, optional + 56, ((len(resources) + 0x1fff) // 0x1000) * 0x1000, 0x200)
    struct.pack_into('<I', headers, optional + 108, 16)
    struct.pack_into('<II', headers, optional + 112 + 2 * 8, 0x1000, len(resources))
    padded = (len(resources) + 0x1ff) // 0x200 * 0x200
    struct.pack_into('<8sIIIIIIHHI', headers, optional + 240, b'.rsrc\0\0\0', len(resources),
                     0x1000, padded, 0x200, 0, 0, 0, 0, 0x40000040)
    return bytes(headers + resources + b'\0' * (padded - len(resources)))
