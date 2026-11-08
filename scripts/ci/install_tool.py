"""Download pinned CI tools and verify the vendor's exact asset checksum."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import tarfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile


TOOLS = {
    "actionlint": ("rhysd/actionlint", "1.7.12"),
    "gitleaks": ("gitleaks/gitleaks", "8.24.2"),
}


def _fetch_release_file(repo: str, version: str, filename: str, timeout: int = 20) -> bytes:
    direct_url = f"https://github.com/{repo}/releases/download/v{version}/{filename}"
    headers = {"User-Agent": "xianyu-pilot-ci-tool-installer/1.0"}
    for attempt in range(1, 3):
        try:
            req = Request(direct_url, headers=headers)
            with urlopen(req, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code == 404:
                break
            time.sleep(1)
        except Exception:
            time.sleep(1)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    api_headers = {
        "User-Agent": "xianyu-pilot-ci-tool-installer/1.0",
        "Accept": "application/vnd.github+json",
    }
    if token:
        api_headers["Authorization"] = f"Bearer {token}"

    api_url = f"https://api.github.com/repos/{repo}/releases/tags/v{version}"
    release_data = None
    for attempt in range(1, 3):
        try:
            req = Request(api_url, headers=api_headers)
            with urlopen(req, timeout=timeout) as response:
                release_data = json.loads(response.read().decode("utf-8"))
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)

    assets = {a["name"]: a["url"] for a in (release_data or {}).get("assets", [])}
    if filename not in assets:
        raise ValueError(f"Asset {filename} not found in release v{version} of {repo}")

    asset_headers = {
        "User-Agent": "xianyu-pilot-ci-tool-installer/1.0",
        "Accept": "application/octet-stream",
    }
    if token:
        asset_headers["Authorization"] = f"Bearer {token}"

    for attempt in range(1, 3):
        try:
            req = Request(assets[filename], headers=asset_headers)
            with urlopen(req, timeout=timeout) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)

    raise RuntimeError(f"Failed to fetch {filename} from {repo} v{version}")


def install(name: str, destination: Path) -> Path:
    repo, version = TOOLS[name]
    windows = platform.system() == "Windows"
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("CI tool installer currently supports x64 runners only")
    system = "windows" if windows else "linux"
    arch = "x64" if name == "gitleaks" else "amd64"
    suffix = "zip" if windows else "tar.gz"
    asset = f"{name}_{version}_{system}_{arch}.{suffix}"
    checksums = _fetch_release_file(repo, version, f"{name}_{version}_checksums.txt").decode("utf-8")
    entries = [line.split() for line in checksums.splitlines()]
    expected = [parts[0] for parts in entries if len(parts) >= 2 and parts[1].lstrip("*").lstrip("./") == asset]
    if len(expected) != 1:
        raise ValueError("Missing or ambiguous vendor checksum")
    archive = _fetch_release_file(repo, version, asset)
    if hashlib.sha256(archive).hexdigest() != expected[0]:
        raise ValueError("CI tool checksum mismatch")
    executable = name + (".exe" if windows else "")
    if windows:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = [n for n in bundle.namelist() if Path(n).name.lower() == executable.lower()]
            if not names:
                raise ValueError("CI tool binary is missing")
            binary = bundle.read(names[0])
    else:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            members = [m for m in bundle.getmembers() if Path(m.name).name == executable and m.isreg()]
            if not members:
                raise ValueError("CI tool binary is missing")
            member = bundle.extractfile(members[0])
            if member is None:
                raise ValueError("CI tool binary is missing")
            binary = member.read()
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / executable
    path.write_bytes(binary)
    path.chmod(0o755)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=TOOLS)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(install(args.tool, args.destination))
