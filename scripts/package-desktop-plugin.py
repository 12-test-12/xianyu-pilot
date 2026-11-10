"""Generate a maintainer key or package a signed plugin for offline distribution."""
import argparse
import os
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.services.desktop_plugins import PACKAGE_FILES, Manifest, read_small


def keygen(private_path, public_path):
    if private_path.resolve() == public_path.resolve() or private_path.exists() or public_path.exists():
        raise ValueError("密钥路径必须不同且尚不存在")
    key = Ed25519PrivateKey.generate()
    with os.fdopen(os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="ascii") as file:
        file.write(key.private_bytes_raw().hex() + "\n")
    with public_path.open("x", encoding="ascii") as file:
        file.write(key.public_key().public_bytes_raw().hex() + "\n")


def package(manifest_path, private_path, output_path):
    manifest = read_small(manifest_path, PACKAGE_FILES["manifest.json"])
    Manifest.model_validate_json(manifest)
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(read_small(private_path, 128).decode("ascii")))
    with ZipFile(output_path, "x", compression=ZIP_DEFLATED) as output:
        output.writestr("manifest.json", manifest)
        output.writestr("manifest.sig", key.sign(manifest).hex())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("keygen")
    generate.add_argument("private_key", type=Path)
    generate.add_argument("public_key", type=Path)
    sign = commands.add_parser("package")
    sign.add_argument("manifest", type=Path)
    sign.add_argument("private_key", type=Path)
    sign.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "keygen":
            keygen(args.private_key, args.public_key)
        else:
            package(args.manifest, args.private_key, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
