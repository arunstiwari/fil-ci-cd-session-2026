"""Wait for a SonarQube analysis to finish and report its quality gate.

The SonarQube Scanner plugin's waitForQualityGate() needs a SonarQube ->
Jenkins webhook. This script needs none: the scanner writes the Compute Engine
task URL to .scannerwork/report-task.txt, so the task can simply be polled.

Reads SONAR_HOST_URL and SONAR_AUTH_TOKEN from the environment, which
withSonarQubeEnv() injects. Writes the raw gate response to
sonar-quality-gate.json.

Exit codes: 0 gate passed, 1 gate failed, 2 gate could not be determined.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

TASK_FILE = ".scannerwork/report-task.txt"
GATE_REPORT = "sonar-quality-gate.json"
POLL_SECONDS = 3
POLL_ATTEMPTS = 60

PASSED, FAILED, UNKNOWN = 0, 1, 2


def _get(url: str, token: str) -> dict:
    """GET a SonarQube API URL with token auth and return the parsed JSON."""
    request = urllib.request.Request(url)
    # SonarQube takes the token as the HTTP basic username with no password.
    basic = base64.b64encode(f"{token}:".encode()).decode()
    request.add_header("Authorization", f"Basic {basic}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def read_task_url() -> str | None:
    """Return the ceTaskUrl the scanner recorded, or None."""
    try:
        with open(TASK_FILE) as fh:
            for line in fh:
                key, _, value = line.strip().partition("=")
                if key == "ceTaskUrl":
                    return value
    except OSError as exc:
        print(f"cannot read {TASK_FILE}: {exc}", file=sys.stderr)
    return None


def wait_for_analysis(task_url: str, token: str) -> str | None:
    """Poll the Compute Engine task until it succeeds; return its analysisId."""
    for _ in range(POLL_ATTEMPTS):
        try:
            task = _get(task_url, token).get("task") or {}
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            print(f"cannot read the analysis task: {exc}", file=sys.stderr)
            return None
        status = task.get("status", "")
        if status == "SUCCESS":
            return task.get("analysisId")
        if status in ("FAILED", "CANCELED"):
            print(f"Sonar analysis task {status}", file=sys.stderr)
            return None
        time.sleep(POLL_SECONDS)
    print("timed out waiting for the analysis task", file=sys.stderr)
    return None


def report(gate: dict) -> int:
    """Print the gate result and return the matching exit code."""
    project_status = gate.get("projectStatus") or {}
    status = project_status.get("status")
    if status == "OK":
        print("SonarQube quality gate: PASSED")
        return PASSED
    if status == "ERROR":
        print("SonarQube quality gate: FAILED")
        for condition in project_status.get("conditions") or []:
            if condition.get("status") == "ERROR":
                print(
                    f"  - {condition.get('metricKey')}: "
                    f"actual={condition.get('actualValue')} "
                    f"{condition.get('comparator')} "
                    f"threshold={condition.get('errorThreshold')}"
                )
        return FAILED
    print(f"could not determine the quality gate: {gate}", file=sys.stderr)
    return UNKNOWN


def main() -> int:
    """Poll the analysis task, then fetch and report the quality gate."""
    base = os.environ.get("SONAR_HOST_URL", "").rstrip("/")
    token = os.environ.get("SONAR_AUTH_TOKEN", "")
    if not base or not token:
        print("SONAR_HOST_URL/SONAR_AUTH_TOKEN are not set", file=sys.stderr)
        return UNKNOWN

    task_url = read_task_url()
    if not task_url:
        return UNKNOWN

    analysis_id = wait_for_analysis(task_url, token)
    if not analysis_id:
        return UNKNOWN

    url = f"{base}/api/qualitygates/project_status?analysisId={analysis_id}"
    try:
        gate = _get(url, token)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        print(f"cannot read the quality gate: {exc}", file=sys.stderr)
        return UNKNOWN

    with open(GATE_REPORT, "w") as fh:
        json.dump(gate, fh, indent=2)
    return report(gate)


if __name__ == "__main__":
    sys.exit(main())
