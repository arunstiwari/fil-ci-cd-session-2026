# python-app — FastAPI CI pipeline demo

A deliberately tiny FastAPI service whose real purpose is to demonstrate an
identical CI pipeline implemented twice: once as a **Jenkins declarative
pipeline** and once as a **GitHub Actions workflow**.

Both pipelines run the same six gates:

| Gate | Tool | Fails the build when |
| --- | --- | --- |
| Lint | `ruff check` | any lint rule is violated |
| Format | `ruff format --check` | code is not formatted |
| Unit tests | `pytest` | any test fails |
| Coverage | `pytest-cov` | total coverage < 90% (`fail_under` in `pyproject.toml`) |
| Docker build + smoke test | `docker build`, `curl /health` | image fails to build or the container never becomes healthy |
| Image scan | Trivy | a **fixable HIGH or CRITICAL** vulnerability is found |

## The application

| Endpoint | Description |
| --- | --- |
| `GET /health` | Liveness probe; returns `{"status": "ok", "version": "..."}` |
| `GET /add?a=&b=` | Returns `{"result": a + b}` |
| `GET /divide?a=&b=` | Returns `{"result": a / b}`, or **400** when `b == 0` |

Business logic lives in `app/calculator.py`, separate from the web layer in
`app/main.py`. That split is what lets the same behaviour be covered by fast
pure unit tests (`tests/test_calculator.py`) and by HTTP-level tests
(`tests/test_main.py`).

## Layout

```
app/calculator.py          pure functions (add, divide)
app/main.py                FastAPI routes
tests/test_calculator.py   unit tests, incl. a parametrized case
tests/test_main.py         API tests via TestClient
pyproject.toml             ruff, pytest and coverage configuration
requirements.txt           runtime dependencies
requirements-dev.txt       runtime + test/lint dependencies
Dockerfile                 multi-stage build, non-root user
Jenkinsfile                Jenkins declarative pipeline
.github/workflows/ci.yml   GitHub Actions workflow
```

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

ruff check .                    # lint
ruff format --check .           # format gate
pytest --cov=app --cov-report=term-missing   # tests + coverage gate

uvicorn app.main:app --reload   # serve on http://127.0.0.1:8000 (docs at /docs)
```

## Container

```bash
docker build -t python-app:local .
docker run --rm -p 8000:8000 python-app:local
curl localhost:8000/health
```

The image is multi-stage: dependencies are installed into a virtualenv in a
builder stage and only that virtualenv plus `app/` are copied into the runtime
stage. The runtime stage applies OS security updates, runs as the non-root user
`appuser` (uid 10001), and declares a `HEALTHCHECK`. Tests and CI config are
excluded via `.dockerignore`.

## Image scanning

```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:0.74.0 image --scanners vuln --ignore-unfixed \
  --severity HIGH,CRITICAL --exit-code 1 python-app:local
```

Both pipelines scan twice on purpose:

1. **Informational pass** — every severity, `--exit-code 0`, archived as a
   report so you can see the full picture.
2. **Gate** — `HIGH,CRITICAL` with `--exit-code 1`, which fails the build.

`--ignore-unfixed` is used so the gate only trips on vulnerabilities that
actually have a fix available; otherwise an unpatched base-image CVE blocks
every build with no action you can take.

> This gate is not theoretical. The first version of this project pinned
> `fastapi==0.115.6`, which resolves `starlette 0.41.3` and tripped the gate on
> three HIGH CVEs. Bumping to `fastapi==0.141.1` (which resolves
> `starlette 1.7.0`) is what made the scan pass — that is the pipeline doing its
> job.

## GitHub Actions

`.github/workflows/ci.yml` runs on pushes to `main`, on pull requests, and via
manual dispatch. Three jobs: `lint` and `test` run in parallel, then `docker`
runs after both pass (`needs: [lint, test]`).

Notable details:

- pip downloads are cached by `actions/setup-python` keyed on `requirements-dev.txt`.
- `ruff check --output-format=github` renders lint findings as inline
  annotations on the diff.
- Coverage percentages are written to the job summary; `junit.xml`,
  `coverage.xml` and `htmlcov/` are uploaded as artifacts.
- The image is built with `load: true` (not pushed) so it can be smoke-tested
  and scanned locally in the runner. Layers are cached via `type=gha`.
- Trivy results are also uploaded as SARIF to GitHub code scanning, which needs
  the `security-events: write` permission declared on the job.

## Jenkins

`Jenkinsfile` is a declarative pipeline with one stage per gate. Point a
Multibranch Pipeline or Pipeline-from-SCM job at this repo; no job
configuration beyond that is required.

**Agent requirements:** `python3` (3.11+) with *either* a working `venv` *or*
`pip3`, plus `docker`, `curl` and `git`. Trivy is optional — see below.

**Plugins:** JUnit is required. The Coverage and HTML Publisher plugins are
optional; the calls to `recordCoverage` and `publishHTML` are wrapped in
`catchError(buildResult: 'SUCCESS')`, so the build still passes without them.

### Running on a containerised Jenkins (docker-out-of-docker)

If Jenkins itself runs in a container that talks to the host's Docker daemon via
the mounted socket, three things behave differently from a native agent. The
pipeline detects and handles all three, but they are worth understanding
because they are the usual causes of a green pipeline turning red on a new
agent.

**1. `python3 -m venv` can exist and still not work.** Debian and Ubuntu split
the stdlib `ensurepip` out of `python3` into the separate `python3-venv`
package. Without it you get:

```
The virtual environment was not created successfully because ensurepip is not
available.  On Debian/Ubuntu systems, you need to install the python3-venv
package
```

Python *is* installed in that situation — only pip's bootstrap is missing. The
`Setup` stage therefore tests for `$VENV/bin/pip` rather than trusting the exit
status of `python3 -m venv`, and falls back to
`pip3 install --target <dir>` with `PYTHONPATH` when the venv is unusable. Both
paths write a `ci-env.sh` that later stages `source`, so the rest of the
pipeline is identical either way.

Two details in that fallback matter:

- Dependencies are installed **outside `$WORKSPACE`** (in `$WORKSPACE_TMP`).
  Installed in-tree, they get walked by `ruff` — which turns a clean lint into
  tens of thousands of findings from third-party code — and shipped into the
  Docker build context.
- `pip install` needs `--break-system-packages` on Debian 13 and other
  PEP 668 "externally managed" Pythons. The flag is added only if the local pip
  advertises it, so older pip versions still work.

The cleaner long-term fix is to install `python3-venv` on the agent so the venv
path is taken. In a custom Jenkins image that is one word:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl jq git unzip ca-certificates gnupg lsb-release \
        python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*
```

**2. A published port is not on the container's `localhost`.** `docker run -p
18000:8000` publishes to the *host*, so `curl localhost:18000` from inside the
Jenkins container connects to nothing. The `Smoke test` stage instead detects
its own Docker network (`docker inspect $(hostname)`) and attaches the
application container to it, then reaches it by container name over Docker's
embedded DNS — no published ports, and no host-port collisions between
concurrent jobs. On a native agent it publishes a port and uses `localhost`; on
the default `bridge` network (which has no embedded DNS) it falls back to
`host.docker.internal`.

**3. `-v "$WORKSPACE:/work"` silently mounts an empty directory.** Volume paths
are resolved by the *daemon*, on the host. `$WORKSPACE` is
`/var/jenkins_home/workspace/...`, which exists only inside the Jenkins
container, so the daemon happily creates an empty directory at that path
instead. The `Image scan` stage therefore never mounts the workspace: it uses
the agent's `trivy` binary when one is present, and its container fallback
redirects stdout on the Jenkins side (`> trivy-report.json`) rather than using
Trivy's `--output`, with the vulnerability DB cached in a **named volume**
(which is daemon-managed and so unaffected).

Note that `docker build` needs no such care — the CLI streams the build context
over the socket, so it reads the workspace from inside the container.

## Verification status

Every gate was executed before being committed, in **both** environments:

- **macOS host (venv path):** ruff clean, 9 tests at 100% coverage, coverage gate
  confirmed to fail at 36% when tests are withheld, image built and
  smoke-tested (healthy, running as uid 10001), Trivy 0 findings, gate exit 0.
- **Containerised Jenkins agent (`pip --target` fallback path):** the original
  `ensurepip` failure reproduced, then all seven stages run from the Jenkinsfile
  verbatim — Setup, Lint, Tests (9 passed / 100%), Docker build, Smoke test
  (reached over the shared Docker network), and Trivy (agent binary, gate exit
  0) with both reports landing in the workspace.

## Deliberately out of scope

This is a CI demo, so there is no CD: nothing is pushed to a registry and
nothing is deployed. The natural next steps would be pushing to a registry with
`docker/login-action` (or Jenkins credentials), signing the image, and adding a
deploy stage gated on a manual approval.
