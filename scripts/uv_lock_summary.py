
import json
import os
import subprocess
import tomllib
import urllib.request
from pathlib import Path


START = "<!-- uv-lock-changes:start -->"
END = "<!-- uv-lock-changes:end -->"


def read_toml(ref: str, filename: str) -> dict:
    result = subprocess.run(
        ["git", "show", f"{ref}:{filename}"],
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        # Missing files are treated as empty.
        if result.stderr.decode().strip():
            print(f"Could not read {filename} at {ref}")
        return {}

    return tomllib.loads(result.stdout.decode())


def packages(ref: str) -> dict[str, set[str]]:
    lock = read_toml(ref, "uv.lock")
    pyproject = read_toml(ref, "pyproject.toml")

    # Automatically identify the root project
    project_name = pyproject.get("project", {}).get("name")

    versions = {}

    for package in lock.get("package", []):
        name = package["name"]

        # Ignore the root project's version
        if name == project_name:
            continue

        versions.setdefault(name, set()).add(
            package["version"]
        )

    return versions


def generate_summary(base_ref: str, head_ref: str) -> str:
    before = packages(base_ref)
    after = packages(head_ref)

    changes = []

    for name in sorted(before.keys() | after.keys()):
        old = ", ".join(sorted(before.get(name, []))) or "—"
        new = ", ".join(sorted(after.get(name, []))) or "—"

        if old != new:
            changes.append(f"- {name} {old} → {new}")

    if not changes:
        return ""

    return (
        "### Changes to the lock file\n\n"
        + "\n".join(changes)
    )


def github_request(method: str, endpoint: str, data=None):
    token = os.environ["GITHUB_TOKEN"]
    api_url = os.environ.get(
        "GITHUB_API_URL", "https://api.github.com"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    payload = None
    if data is not None:
        payload = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{api_url}{endpoint}",
        data=payload,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(request) as response:
        return json.load(response)


def update_pr_body(body: str, summary: str) -> str:
    # Remove existing summary section
    if START in body and END in body:
        start = body.index(START)
        end = body.index(END, start) + len(END)

        body = (
            body[:start] + body[end:]
        ).strip()

    # Only add summary if dependencies changed
    if summary:
        section = f"{START}\n{summary}\n{END}"
        body = f"{body}\n\n{section}".strip()

    return body


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    pr_number = os.environ["PR_NUMBER"]

    summary = generate_summary(
        "HEAD",
        "refs/remotes/origin/pr-head",
    )

    endpoint = f"/repos/{repository}/pulls/{pr_number}"

    # Fetch current PR description
    pr = github_request("GET", endpoint)
    original_body = pr.get("body") or ""

    # Generate updated description
    updated_body = update_pr_body(original_body, summary)

    if updated_body == original_body:
        print("No PR description changes required.")
        return

    # Update PR description
    github_request(
        "PATCH",
        endpoint,
        {"body": updated_body},
    )

    print("PR description updated successfully.")


if __name__ == "__main__":
    main()
