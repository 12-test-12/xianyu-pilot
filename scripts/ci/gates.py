"""Fail closed when required jobs or CodeQL reports do not pass."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys


def check_jobs(jobs: dict, required: list[str]) -> list[str]:
    if not isinstance(jobs, dict) or not required or set(jobs) != set(required):
        raise ValueError("The quality gate must receive exactly the required jobs")
    return [name for name in required if jobs[name].get("result") != "success"]


def check_sarif(directory: Path, threshold: float = 7.0) -> tuple[int, int]:
    if not math.isfinite(threshold) or not 0 <= threshold <= 10:
        raise ValueError("Invalid security severity threshold")
    reports = sorted(directory.rglob("*.sarif"))
    if not reports:
        raise ValueError("CodeQL produced no SARIF reports")
    total = blocked = 0
    for path in reports:
        data = json.loads(path.read_text(encoding="utf-8"))
        runs = data.get("runs")
        if data.get("version") != "2.1.0" or not isinstance(runs, list) or not runs:
            raise ValueError("Invalid SARIF document")
        for run in runs:
            for invocation in run.get("invocations", []):
                if invocation.get("executionSuccessful") is False:
                    raise ValueError("CodeQL execution failed")
                if any(n.get("level") == "error" for n in invocation.get("toolExecutionNotifications", [])):
                    raise ValueError("CodeQL reported an execution error")
            tool = run["tool"]
            rules = tool["driver"].get("rules", [])
            rule_map = {r["id"]: r for r in rules}
            for extension in tool.get("extensions", []):
                for rule in extension.get("rules", []):
                    rule_map.setdefault(rule["id"], rule)
            results = run.get("results")
            if not isinstance(results, list):
                raise ValueError("SARIF results are missing")
            for result in results:
                if "ruleId" in result:
                    rule = rule_map[result["ruleId"]]
                else:
                    index = result["ruleIndex"]
                    if type(index) is not int or not 0 <= index < len(rules):
                        raise ValueError("Invalid SARIF rule index")
                    rule = rules[index]
                score = rule.get("properties", {}).get("security-severity")
                if score is not None:
                    score = float(score)
                    if not math.isfinite(score) or not 0 <= score <= 10:
                        raise ValueError("Invalid SARIF severity")
                    blocking = score >= threshold
                else:
                    blocking = result.get("level", rule.get("defaultConfiguration", {}).get("level")) == "error"
                total += 1
                blocked += bool(blocking)
    return total, blocked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    jobs = sub.add_parser("jobs")
    jobs.add_argument("required", nargs="+")
    sarif = sub.add_parser("sarif")
    sarif.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "jobs":
            jobs = json.loads(os.environ["JOB_RESULTS"])
            failed = check_jobs(jobs, args.required)
            summary = "| Check | Result |\n| --- | --- |\n" + "".join(
                f"| {name} | {jobs[name]['result']} |\n" for name in args.required
            )
            if os.environ.get("GITHUB_STEP_SUMMARY"):
                with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
                    stream.write("## Quality gate\n\n" + summary)
            print("Blocked checks: " + ", ".join(failed) if failed else "All required checks passed")
            return int(bool(failed))
        total, blocked = check_sarif(args.directory)
        print(f"CodeQL: {total} findings, {blocked} blocking findings (severity >= 7 or unscored error)")
        return int(bool(blocked))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # Reports can contain source text. Never echo their bodies on failure.
        print("Quality gate received invalid or incomplete evidence", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
