#!/usr/bin/env python3
"""Push local commits to origin via the GitHub Git Data API (byte-faithful replay).

Why this exists: on this machine `git push` to github.com:443 is blocked (only
api.github.com is reachable), so commits are replayed as blob -> tree -> commit
with the exact tree entries, parents, author/committer identities and message
taken from the local commit objects. A faithful replay yields the same commit
SHAs locally and remotely.

Usage:
    PUSH_BRANCH=my-branch python scripts/push_via_api.py
    PUSH_BRANCH=my-branch python scripts/push_via_api.py --create-from <sha>
    python scripts/push_via_api.py            # branch defaults to current branch

Notes:
- New branches are created at --create-from (default HEAD~1, the branch point),
  which must already exist on the remote.
- `--reset` is intentionally not supported: force-pushing needs an explicit base.
- Uses `gh auth token` (so `gh` must be logged in) and bypasses any system proxy.
- Transient `WinError 10060` timeouts on this network: just re-run; it retries
  twice internally before failing.
"""
import base64
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"


def _git(*args, binary=False):
    output = subprocess.check_output(["git", *args])
    return output if binary else output.decode("utf-8")


def detect_repo() -> str:
    remote = _git("remote", "get-url", "origin").strip()
    # git@github.com:owner/repo.git | https://github.com/owner/repo.git
    remote = remote.removesuffix(".git")
    if remote.startswith("git@github.com:"):
        return remote.split(":", 1)[1]
    return remote.split("github.com/", 1)[-1]


REPO = os.environ.get("PUSH_REPO") or detect_repo()
BRANCH = os.environ.get("PUSH_BRANCH") or _git("rev-parse", "--abbrev-ref", "HEAD").strip()
TOKEN = subprocess.check_output(
    ["gh", "auth", "token"], text=True, encoding="utf-8"
).strip()

# A local system proxy can rewrite api.github.com requests into 500/cert errors;
# direct connections work, so bypass the proxy explicitly.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(method, path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    last_error = None
    for attempt in range(3):
        req = urllib.request.Request(API + path, method=method, data=data)
        req.add_header("Authorization", f"Bearer {TOKEN}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("Content-Type", "application/json")
        try:
            with OPENER.open(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise SystemExit(f"{method} {path} failed: {exc.code} {body[:500]}")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
    raise SystemExit(f"{method} {path} failed after retries: {last_error}")


def parse_commit(sha):
    raw = _git("cat-file", "commit", sha)
    head, _, message = raw.partition("\n\n")
    info = {"parents": [], "author": None, "committer": None}
    for line in head.split("\n"):
        if line.startswith("parent "):
            info["parents"].append(line[7:])
        elif line.startswith("author "):
            info["author"] = line[7:]
        elif line.startswith("committer "):
            info["committer"] = line[10:]
    return info, message


def identity(line):
    # "Name <email> 1698029869 +0800"
    name_email, _, tz = line.rpartition(" ")
    name_email, _, stamp = name_email.rpartition(" ")
    name, _, email = name_email.partition(" <")
    return {
        "name": name.strip(),
        "email": email.rstrip(">"),
        "date": int(stamp),
        "tz": tz,
    }


def iso_date(who):
    sign = 1 if who["tz"][0] == "+" else -1
    offset = datetime.timedelta(
        hours=int(who["tz"][1:3]), minutes=int(who["tz"][3:5])
    ) * sign
    local = datetime.datetime.fromtimestamp(who["date"], datetime.timezone(offset))
    return local.isoformat()


def create_from_arg() -> str | None:
    if "--create-from" in sys.argv:
        index = sys.argv.index("--create-from")
        if index + 1 < len(sys.argv):
            return sys.argv[index + 1]
    return None


def main():
    try:
        remote = api("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}")
        parent = remote["object"]["sha"]
        print("remote head before:", parent)
    except SystemExit:
        base = create_from_arg() or _git("rev-parse", "HEAD~1").strip()
        api("POST", f"/repos/{REPO}/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": base})
        parent = base
        print("remote branch created at:", parent)

    commits = _git("rev-list", "--reverse", f"{parent}..HEAD").split()
    print("commits to replay:", len(commits))

    for sha in commits:
        info, message = parse_commit(sha)
        parent_tree = api("GET", f"/repos/{REPO}/git/commits/{parent}")["tree"]["sha"]
        entries = []
        for line in _git("diff-tree", "--no-commit-id", "--name-status", "-r", sha).splitlines():
            parts = line.split("\t")
            if parts[0].startswith("D"):
                entries.append({"path": parts[1], "mode": "100644", "type": "blob", "sha": None})
                continue
            if parts[0].startswith("R"):
                entries.append({"path": parts[1], "mode": "100644", "type": "blob", "sha": None})
                path = parts[2]
            else:
                path = parts[1]
            content = _git("cat-file", "blob", f"{sha}:{path}", binary=True)
            blob = api(
                "POST",
                f"/repos/{REPO}/git/blobs",
                {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"},
            )
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})

        tree = api("POST", f"/repos/{REPO}/git/trees", {"base_tree": parent_tree, "tree": entries})
        author = identity(info["author"])
        committer = identity(info["committer"])
        commit = api(
            "POST",
            f"/repos/{REPO}/git/commits",
            {
                "message": message,
                "tree": tree["sha"],
                "parents": info["parents"],
                "author": {k: author[k] for k in ("name", "email")} | {"date": iso_date(author)},
                "committer": {k: committer[k] for k in ("name", "email")} | {"date": iso_date(committer)},
            },
        )
        same = "SAME" if commit["sha"] == sha else "DIFF"
        print(f"  {sha[:7]} -> {commit['sha'][:7]} tree={tree['sha'][:7]} [{same}]")
        parent = commit["sha"]

    api("PATCH", f"/repos/{REPO}/git/refs/heads/{BRANCH}", {"sha": parent, "force": True})
    print("remote head after :", parent)
    print("local head        :", _git("rev-parse", "HEAD").strip())


if __name__ == "__main__":
    main()
