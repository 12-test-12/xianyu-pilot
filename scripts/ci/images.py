"""Validate image identities and promote only a complete set of build digests."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


COMPONENTS = ("api", "web", "crawler")


def namespace(value: str) -> str:
    value = value.lower()
    if not re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)*", value):
        raise ValueError("Invalid registry namespace")
    return value


def image_name(owner: str, component: str) -> str:
    if component not in COMPONENTS:
        raise ValueError("Unknown image component")
    return f"ghcr.io/{namespace(owner)}/xianyu-assistant-{component}"


def revision(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Expected full source revision")
    return value


def release_tag(ref: str) -> str:
    ref = ref.strip()
    if ref == "refs/heads/main":
        return "latest"
    prefix = "refs/tags/"
    if ref.startswith(prefix + "v"):
        tag = ref[len(prefix):]
        if re.fullmatch(r"v[0-9][A-Za-z0-9_.-]{0,126}", tag):
            return tag
    raise ValueError("Image publishing is restricted to main and version tags")


def validate_manifests(directory: Path, owner: str, sha: str) -> list[dict]:
    revision(sha)
    records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]
    if len(records) != len(COMPONENTS) or {r["component"] for r in records} != set(COMPONENTS):
        raise ValueError("All three component digests are required before promotion")
    for record in records:
        if record["revision"] != sha or record["image"] != image_name(owner, record["component"]):
            raise ValueError("Image evidence belongs to a different source or namespace")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", record["digest"]):
            raise ValueError("Invalid image digest")
    return records


def promotion_commands(records: list[dict], tag: str, acr_registry: str = "", acr_namespace: str = "") -> list[list[str]]:
    if not re.fullmatch(r"(?:latest|v[0-9][A-Za-z0-9_.-]{0,126})", tag):
        raise ValueError("Invalid release tag")
    if bool(acr_registry) != bool(acr_namespace):
        raise ValueError("Incomplete ACR configuration")
    if acr_registry and not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)+", acr_registry):
        raise ValueError("ACR registry must be a hostname without scheme or path")
    commands = []
    for record in records:
        source = f"{record['image']}@{record['digest']}"
        commands.append(["docker", "buildx", "imagetools", "create", "--tag", f"{record['image']}:{tag}", source])
        if acr_registry:
            target = f"{acr_registry}/{namespace(acr_namespace)}/xianyu-assistant-{record['component']}"
            commands.append([
                "docker", "buildx", "imagetools", "create",
                "--tag", f"{target}:sha-{record['revision']}", "--tag", f"{target}:{tag}", source,
            ])
    return commands


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "record", "promote", "registry"))
    parser.add_argument("--component", choices=COMPONENTS)
    parser.add_argument("--directory", type=Path, default=Path("reports/images"))
    args = parser.parse_args()
    if args.command == "registry":
        values = [os.environ.get(key, "") for key in ("ACR_REGISTRY", "ACR_NAMESPACE", "ACR_USERNAME", "ACR_PASSWORD")]
        if any(values) and not all(values):
            raise ValueError("Configure all four ACR settings or leave all unset")
        if all(values):
            # Validate public settings without ever writing credential values.
            promotion_commands([], "latest", values[0], values[1])
            namespace(values[1])
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"enabled={'true' if all(values) else 'false'}\n")
        return
    owner = os.environ.get("GHCR_NAMESPACE") or os.environ["GITHUB_REPOSITORY_OWNER"]
    sha = revision(os.environ["GITHUB_SHA"])
    release_tag(os.environ["GITHUB_REF"])
    if args.command == "prepare":
        image = image_name(owner, args.component)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"image={image}\ntag={image}:sha-{sha}\n")
    elif args.command == "record":
        record = {"component": args.component, "revision": sha, "image": image_name(owner, args.component), "digest": os.environ["IMAGE_DIGEST"]}
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", record["digest"]):
            raise ValueError("Build did not return a valid image digest")
        args.directory.mkdir(parents=True, exist_ok=True)
        (args.directory / f"{args.component}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    else:
        records = validate_manifests(args.directory, owner, sha)
        if os.environ["GITHUB_REF"] == "refs/heads/main":
            current_main_sha = os.environ.get("CURRENT_MAIN_SHA", "").strip().lower()
            if current_main_sha:
                current = revision(current_main_sha)
                if current != sha:
                    message = "Source is no longer current main; revision images are retained, latest promotion is skipped."
                    print(message)
                    if os.environ.get("GITHUB_STEP_SUMMARY"):
                        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                            summary.write(message + "\n")
                    return
        commands = promotion_commands(records, release_tag(os.environ["GITHUB_REF"]), os.environ.get("ACR_REGISTRY", ""), os.environ.get("ACR_NAMESPACE", ""))
        for command in commands:
            subprocess.run(command, check=True)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                summary.write("## Published images\n\n| Image | Digest |\n| --- | --- |\n")
                for record in records:
                    summary.write(f"| {record['image']} | `{record['digest']}` |\n")


if __name__ == "__main__":
    main()
