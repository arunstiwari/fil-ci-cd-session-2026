// Declarative pipeline mirroring .github/workflows/ci.yml
//
// Agent requirements: python3 (3.11+) with either the venv module or pip,
// docker, curl, git. Trivy is used from the agent if installed, otherwise it is
// pulled as a container. Plugins: JUnit required; Coverage and HTML Publisher
// optional.
//
// This pipeline is written to survive two very common agent setups:
//   1. A native agent (venv available, published ports reachable on localhost).
//   2. Jenkins running inside a Docker container talking to the host daemon
//      ("docker-out-of-docker"), where the workspace path does not exist on the
//      host and published ports are NOT on the container's localhost.
// See the "Setup" and "Smoke test" stages for how each is detected.

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
    }

    environment {
        IMAGE_NAME  = 'python-app'
        IMAGE_TAG   = "${env.BUILD_NUMBER}-${env.GIT_COMMIT ? env.GIT_COMMIT.take(7) : 'local'}"
        TRIVY_IMAGE = 'aquasec/trivy:0.74.0'
        PIP_DISABLE_PIP_VERSION_CHECK = '1'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                sh 'git --no-pager log -1 --oneline || true'
            }
        }

        stage('Setup') {
            steps {
                // Python deps are installed OUTSIDE $WORKSPACE, so that ruff and
                // pytest never walk into them and docker build does not ship them.
                sh '''
                    set -eu
                    DEPS_ROOT="${WORKSPACE_TMP:-${TMPDIR:-/tmp}}"
                    VENV_DIR="$DEPS_ROOT/venv"
                    PYDEPS_DIR="$DEPS_ROOT/pydeps"
                    rm -rf "$VENV_DIR" "$PYDEPS_DIR"

                    python3 -V

                    # Prefer a virtualenv. On Debian/Ubuntu the stdlib ensurepip is
                    # split into the python3-venv package, so `python3 -m venv` can
                    # exist yet produce an unusable venv with no pip in it. Testing
                    # for that pip is the only reliable check.
                    if python3 -m venv "$VENV_DIR" >/dev/null 2>&1 && [ -x "$VENV_DIR/bin/pip" ]; then
                        echo "Using virtualenv at $VENV_DIR"
                        "$VENV_DIR/bin/pip" install --upgrade pip
                        "$VENV_DIR/bin/pip" install -r requirements-dev.txt
                        printf 'export PATH="%s/bin:$PATH"\\n' "$VENV_DIR" > ci-env.sh
                    else
                        rm -rf "$VENV_DIR"
                        echo "venv unusable on this agent (ensurepip/python3-venv missing);"
                        echo "falling back to 'pip install --target $PYDEPS_DIR'"
                        command -v pip3 >/dev/null 2>&1 || {
                            echo "FATAL: neither a working venv nor pip3 is available." >&2
                            echo "Install python3-venv (or python3-pip) on the agent." >&2
                            exit 1
                        }
                        # PEP 668 marks distro Pythons "externally managed"; the flag
                        # is only needed (and only exists) on newer pip.
                        PIP_EXTRA=""
                        if pip3 install --help 2>/dev/null | grep -q -- --break-system-packages; then
                            PIP_EXTRA="--break-system-packages"
                        fi
                        pip3 install $PIP_EXTRA --root-user-action=ignore \
                            --target "$PYDEPS_DIR" -r requirements-dev.txt
                        {
                            printf 'export PYTHONPATH="%s"\\n' "$PYDEPS_DIR"
                            printf 'export PATH="%s/bin:$PATH"\\n' "$PYDEPS_DIR"
                        } > ci-env.sh
                    fi

                    . ./ci-env.sh
                    echo "ruff:   $(ruff --version)"
                    echo "pytest: $(pytest --version 2>&1 | head -1)"
                '''
            }
        }

        stage('Lint') {
            steps {
                sh '''
                    set -eu
                    . ./ci-env.sh
                    ruff check --output-format=concise . | tee ruff-report.txt
                    ruff format --check .
                '''
            }
            post {
                always {
                    archiveArtifacts artifacts: 'ruff-report.txt', allowEmptyArchive: true
                }
            }
        }

        stage('Unit tests & coverage') {
            steps {
                sh '''
                    set -eu
                    . ./ci-env.sh
                    pytest \
                      --junitxml=junit.xml \
                      --cov=app \
                      --cov-report=term-missing \
                      --cov-report=xml \
                      --cov-report=html
                '''
            }
            post {
                always {
                    junit testResults: 'junit.xml', allowEmptyResults: false
                    archiveArtifacts artifacts: 'coverage.xml, htmlcov/**', allowEmptyArchive: true
                    // Optional plugins: never fail the build if they are absent.
                    catchError(buildResult: 'SUCCESS', stageResult: 'SUCCESS', message: 'Coverage plugin unavailable') {
                        recordCoverage(tools: [[parser: 'COBERTURA', pattern: 'coverage.xml']])
                    }
                    catchError(buildResult: 'SUCCESS', stageResult: 'SUCCESS', message: 'HTML Publisher unavailable') {
                        publishHTML(target: [
                            reportDir: 'htmlcov',
                            reportFiles: 'index.html',
                            reportName: 'Coverage report',
                            keepAll: true,
                            allowMissing: true,
                            alwaysLinkToLastBuild: true
                        ])
                    }
                }
            }
        }

        stage('Docker build') {
            steps {
                // The build context is streamed to the daemon by the CLI, so this
                // works unchanged under docker-out-of-docker.
                sh '''
                    set -eu
                    docker build -t "$IMAGE_NAME:$IMAGE_TAG" -t "$IMAGE_NAME:latest" .
                    docker image inspect "$IMAGE_NAME:$IMAGE_TAG" --format 'built {{.Id}} size={{.Size}}'
                '''
            }
        }

        stage('Smoke test image') {
            steps {
                sh '''
                    set -eu
                    IMG="$IMAGE_NAME:$IMAGE_TAG"
                    NAME="smoke-$BUILD_NUMBER"
                    docker rm -f "$NAME" >/dev/null 2>&1 || true

                    # When Jenkins itself is a container, a published port lands on
                    # the *host*, not on this container's localhost. Attaching the
                    # smoke container to our own user-defined network instead lets us
                    # reach it by container name over Docker's embedded DNS, with no
                    # published ports and no host-port collisions.
                    NET=""
                    if [ -f /.dockerenv ]; then
                        NET=$(docker inspect -f \
                          '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' \
                          "$(hostname)" 2>/dev/null | awk '{print $1}') || NET=""
                    fi

                    if [ -n "$NET" ] && [ "$NET" != "bridge" ]; then
                        echo "containerised Jenkins; joining network '$NET'"
                        docker run -d --name "$NAME" --network "$NET" "$IMG" >/dev/null
                        URL="http://$NAME:8000/health"
                    elif [ -f /.dockerenv ]; then
                        # Only the default bridge (no embedded DNS) - go via the host.
                        echo "containerised Jenkins on default bridge; using host gateway"
                        docker run -d --name "$NAME" -p 18000:8000 "$IMG" >/dev/null
                        URL="http://host.docker.internal:18000/health"
                    else
                        docker run -d --name "$NAME" -p 18000:8000 "$IMG" >/dev/null
                        URL="http://localhost:18000/health"
                    fi

                    echo "probing $URL"
                    ok=0
                    for _ in $(seq 1 15); do
                        if curl -fsS "$URL"; then ok=1; break; fi
                        sleep 2
                    done
                    if [ "$ok" -ne 1 ]; then
                        echo ""
                        echo "service did not become healthy"
                        docker logs "$NAME" || true
                        exit 1
                    fi
                    echo ""
                    echo "service healthy"
                '''
            }
            post {
                always {
                    sh 'docker rm -f "smoke-$BUILD_NUMBER" >/dev/null 2>&1 || true'
                }
            }
        }

        stage('Image scan (Trivy)') {
            steps {
                sh '''
                    set -eu
                    IMG="$IMAGE_NAME:$IMAGE_TAG"

                    # Use the agent's trivy when present. The container fallback
                    # deliberately mounts NO workspace path: under
                    # docker-out-of-docker $WORKSPACE does not exist on the host, so
                    # such a mount silently yields an empty directory. Reports are
                    # captured by redirecting stdout on the Jenkins side instead, and
                    # the vulnerability DB is cached in a named volume.
                    if command -v trivy >/dev/null 2>&1; then
                        TRIVY="trivy"
                        echo "using agent trivy: $(trivy --version | head -1)"
                    else
                        TRIVY="docker run --rm \
                            -v /var/run/docker.sock:/var/run/docker.sock \
                            -v trivy-cache:/root/.cache $TRIVY_IMAGE"
                        echo "using $TRIVY_IMAGE"
                    fi

                    # Informational pass: every severity, never fails the build.
                    $TRIVY image --scanners vuln --ignore-unfixed \
                        --severity LOW,MEDIUM,HIGH,CRITICAL \
                        --format table --exit-code 0 "$IMG" | tee trivy-report.txt

                    $TRIVY image --scanners vuln --ignore-unfixed \
                        --format json --exit-code 0 "$IMG" > trivy-report.json

                    # Gate: fail on fixable HIGH/CRITICAL findings.
                    $TRIVY image --scanners vuln --ignore-unfixed \
                        --severity HIGH,CRITICAL --exit-code 1 \
                        --format table "$IMG"
                '''
            }
            post {
                always {
                    archiveArtifacts artifacts: 'trivy-report.txt, trivy-report.json', allowEmptyArchive: true
                }
            }
        }
    }

    post {
        always {
            sh '''
                DEPS_ROOT="${WORKSPACE_TMP:-${TMPDIR:-/tmp}}"
                docker rm -f "smoke-$BUILD_NUMBER" >/dev/null 2>&1 || true
                docker rmi "$IMAGE_NAME:$IMAGE_TAG" >/dev/null 2>&1 || true
                rm -rf "$DEPS_ROOT/venv" "$DEPS_ROOT/pydeps" || true
            '''
            cleanWs(notFailBuild: true)
        }
        success {
            echo "CI passed for ${env.IMAGE_NAME}:${env.IMAGE_TAG}"
        }
        failure {
            echo 'CI failed - check the stage logs and archived reports.'
        }
    }
}
