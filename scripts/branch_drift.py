#!/usr/bin/env python3
"""Report branch work that exists outside main and is not in an open PR.

The release runner only sees main. A branch with commits main does not have,
and no open pull request, is work that can never reach a tenant. This check
makes that state visible and fails a scheduled run when it persists.

Usage:
    python scripts/branch_drift.py                  # report
    python scripts/branch_drift.py --max-age 7      # fail when older than 7 days
    python scripts/branch_drift.py --json           # machine-readable
    python scripts/branch_drift.py --list-merged    # branches safe to delete

Reads the local remote-tracking refs for `origin`; call `git fetch --prune`
first. Open pull requests are read from the GitHub API using GITHUB_TOKEN when
present (public read works without it, at a lower rate limit).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "origin"
BASE = f"{REMOTE}/main"


@dataclass
class Branch:
    name: str
    ahead: int
    last_commit_ts: int
    author: str
    subject: str
    pr: int | None = None

    @property
    def age_days(self) -> int:
        return max(0, int((time.time() - self.last_commit_ts) // 86400))


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def remote_branches() -> list[str]:
    out = git("for-each-ref", "--format=%(refname:short)", f"refs/remotes/{REMOTE}")
    return [line.strip() for line in out.splitlines() if line.strip() and line.strip() != BASE]


def describe(name: str) -> Branch | None:
    ahead = int(git("rev-list", "--count", f"{BASE}..{name}").strip() or 0)
    if ahead == 0:
        return None
    raw = git("log", "-1", "--format=%ct%x00%an%x00%s", name).rstrip("\n")
    ts, author, subject = raw.split("\x00", 2)
    return Branch(name.removeprefix(f"{REMOTE}/"), ahead, int(ts), author, subject)


def open_pull_requests() -> dict[str, int]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not repository:
        try:
            url = git("remote", "get-url", REMOTE).strip()
            slug = url.split("github.com", 1)[-1].lstrip(":/").removesuffix(".git")
            repository = "/".join(slug.split("/")[-2:])
        except subprocess.CalledProcessError:
            return {}
    if "/" not in repository:
        return {}
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "branch-drift"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    prs: dict[str, int] = {}
    page = 1
    while True:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/pulls"
            f"?state=open&per_page=100&page={page}",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                batch = json.load(response)
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            print(f"warning: could not read open pull requests: {exc}", file=sys.stderr)
            return prs
        for item in batch:
            prs[str(item.get("head", {}).get("ref") or "")] = int(item["number"])
        if len(batch) < 100:
            return prs
        page += 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age", type=int, default=None,
                        help="fail when an orphan branch is older than this many days")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list-merged", action="store_true",
                        help="list branches fully contained in main instead of the report")
    args = parser.parse_args()

    branches = remote_branches()
    merged: list[str] = []
    live: list[Branch] = []
    for name in branches:
        branch = describe(name)
        if branch is None:
            merged.append(name.removeprefix(f"{REMOTE}/"))
        else:
            live.append(branch)

    if args.list_merged:
        for name in sorted(merged):
            print(name)
        return 0

    prs = open_pull_requests()
    orphans: list[Branch] = []
    for branch in live:
        branch.pr = prs.get(branch.name)
        if branch.pr is None:
            orphans.append(branch)

    report = {
        "branches": len(branches),
        "merged_into_main": len(merged),
        "ahead_of_main": len(live),
        "in_open_pr": len(live) - len(orphans),
        "orphaned": len(orphans),
        "orphaned_older_than_7d": sum(1 for b in orphans if b.age_days > 7),
        "oldest_orphan_days": max((b.age_days for b in orphans), default=0),
    }

    if args.json:
        print(json.dumps({**report, "orphans": [
            {"branch": b.name, "ahead": b.ahead, "age_days": b.age_days,
             "author": b.author, "subject": b.subject}
            for b in sorted(orphans, key=lambda b: -b.age_days)
        ]}, indent=2))
    else:
        print(f"branches: {report['branches']}  "
              f"merged into main: {report['merged_into_main']}  "
              f"ahead of main: {report['ahead_of_main']}  "
              f"in an open PR: {report['in_open_pr']}  "
              f"orphaned: {report['orphaned']}")
        if orphans:
            print("\nwork with no path to main (branch, commits ahead, age, last commit):")
            for branch in sorted(orphans, key=lambda b: -b.age_days):
                print(f"  {branch.age_days:>4}d  +{branch.ahead:<3} {branch.name}  "
                      f"{branch.subject[:70]}")
        if merged:
            print(f"\n{len(merged)} branches are fully in main and safe to delete "
                  f"(--list-merged)")

    if args.max_age is not None:
        stale = [b for b in orphans if b.age_days > args.max_age]
        if stale:
            print(f"\n{len(stale)} orphaned branch(es) older than {args.max_age} days.",
                  file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
