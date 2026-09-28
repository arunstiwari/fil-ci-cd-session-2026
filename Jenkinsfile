// Declarative pipeline mirroring .github/workflows/ci.yml
// Requires on the agent: python3, docker. Plugins: JUnit, Warnings NG (optional),
// Coverage (optional), HTML Publisher (optional).

pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
    }

    environment {
        IMAGE_NAME   = 'python-app'
        IMAGE_TAG    = "${env.BUILD_NUMBER}-${env.GIT_COMMIT ? env.GIT_COMMIT.take(7) : 'local'}"
        VENV         = '.venv'
        PIP_NO_CACHE_DIR = '1'
        TRIVY_VERSION = '0.74.0'
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
                sh '''
                    set -eu
                    python3 -m venv "$VENV"
                    . "$VENV/bin/activate"
                    pip install --upgrade pip
                    pip install -r requirements-dev.txt
                '''
            }
        }

        stage('Lint') {
            steps {
                sh '''
                    set -eu
                    . "$VENV/bin/activate"
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
                    . "$VENV/bin/activate"
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
                    // Optional plugins: never fail the build if they are not installed.
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
                    docker rm -f smoke-$BUILD_NUMBER >/dev/null 2>&1 || true
                    docker run -d --name "smoke-$BUILD_NUMBER" -p 18000:8000 "$IMAGE_NAME:$IMAGE_TAG"
                    ok=0
                    for _ in $(seq 1 15); do
                        if curl -fsS http://localhost:18000/health; then ok=1; break; fi
                        sleep 2
                    done
                    if [ "$ok" -ne 1 ]; then
                        docker logs "smoke-$BUILD_NUMBER"
                        exit 1
                    fi
                    echo "\nservice healthy"
                '''
            }
            post {
                always {
                    sh 'docker rm -f smoke-$BUILD_NUMBER >/dev/null 2>&1 || true'
                }
            }
        }

        stage('Image scan (Trivy)') {
            steps {
                sh '''
                    set -eu
                    mkdir -p "$WORKSPACE/.trivycache"

                    trivy_run() {
                        docker run --rm \
                          -v /var/run/docker.sock:/var/run/docker.sock \
                          -v "$WORKSPACE/.trivycache:/root/.cache" \
                          -v "$WORKSPACE:/work" -w /work \
                          "aquasec/trivy:$TRIVY_VERSION" "$@"
                    }

                    # Informational pass: everything we found, never fails the build.
                    trivy_run image --scanners vuln --ignore-unfixed \
                      --severity LOW,MEDIUM,HIGH,CRITICAL \
                      --format table --exit-code 0 "$IMAGE_NAME:$IMAGE_TAG" | tee trivy-report.txt

                    trivy_run image --scanners vuln --ignore-unfixed \
                      --format json --output trivy-report.json \
                      --exit-code 0 "$IMAGE_NAME:$IMAGE_TAG"

                    # Gate: fail the build on fixable HIGH/CRITICAL findings.
                    trivy_run image --scanners vuln --ignore-unfixed \
                      --severity HIGH,CRITICAL --exit-code 1 \
                      --format table "$IMAGE_NAME:$IMAGE_TAG"
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
                docker rmi "$IMAGE_NAME:$IMAGE_TAG" >/dev/null 2>&1 || true
                rm -rf "$VENV"
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
