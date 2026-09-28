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

**Agent requirements:** `python3` (3.11+), `docker`, `curl`, and network access
to PyPI and Docker Hub. Trivy is *not* installed on the agent — it runs from the
`aquasec/trivy` container, with the Docker socket mounted so it can read the
image from the local daemon and the Trivy DB cached in the workspace.

**Plugins:** JUnit is required. The Coverage and HTML Publisher plugins are
optional — the calls to `recordCoverage` and `publishHTML` are wrapped in
`catchError(buildResult: 'SUCCESS')`, so the build still passes if they are not
installed.

The smoke-test stage publishes on host port `18000` rather than `8000` to avoid
colliding with anything else on the agent, and the container name includes
`$BUILD_NUMBER` so concurrent-ish builds cannot clash. Cleanup of the container,
the built image and the virtualenv happens in `post { always { ... } }`, so it
runs even when an earlier stage fails.

## Verification status

Every gate in this repo was executed locally before being committed: ruff clean,
9 tests passing at 100% coverage, image built and smoke-tested (returning
healthy and running as uid 10001), and Trivy reporting 0 findings with the
HIGH/CRITICAL gate exiting 0.

## Deliberately out of scope

This is a CI demo, so there is no CD: nothing is pushed to a registry and
nothing is deployed. The natural next steps would be pushing to a registry with
`docker/login-action` (or Jenkins credentials), signing the image, and adding a
deploy stage gated on a manual approval.
