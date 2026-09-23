# SonarQube Analysis

This repository is analysed by [SonarQube Cloud](https://sonarcloud.io) on every
push and pull request, and the same analysis can be run locally.

Project configuration lives in [`sonar-project.properties`](../sonar-project.properties).

## What is analysed

| Property | Value |
| --- | --- |
| Organization | `ventura8` |
| Project key | `ventura8_Auto-VHS-Deinterlacer` |
| Sources | `auto_deinterlancer.py`, `modules`, `tools`, `.github/scripts` |
| Tests | `tests` |
| Coverage report | `assets/coverage.xml` (Cobertura, from `pytest-cov`) |
| Test execution report | `assets/pytest-report.xml` (JUnit, from `pytest --junitxml`) |

Excluded: `.venv`, `input`, `assets`, `docker`, `__pycache__` and generated
`.vpy` scripts — none of these carry reviewable source.

## CI

The `Run SonarQube Cloud Scan` step runs at the end of the
`🔍🧪📊 Unified Quality Pipeline` job, after coverage has been produced. It
passes `-Dsonar.qualitygate.wait=true`, so a failing quality gate fails the
build.

Two prerequisites on the GitHub repository:

1. A `SONAR_TOKEN` repository secret
   (SonarQube Cloud → *My Account* → *Security* → *Generate Token*).
1. The checkout uses `fetch-depth: 0` so Sonar can attribute issues to new code.

When `SONAR_TOKEN` is absent the scan step is skipped with a build warning
rather than failing. This keeps the pipeline green before the secret is
configured, and on pull requests from forks, which never receive secrets.

Automatic Analysis must stay **off** for this project
(*Administration* → *Analysis method*). It cannot ingest `coverage.xml`, and
leaving it on makes the CI scan fail as a duplicate analysis.

## Running locally

Use the helper script — it regenerates coverage and runs the scanner from the
official Docker image, so no local Java or `sonar-scanner` install is needed:

```bash
export SONAR_TOKEN=<your-sonarcloud-token>
./tools/run_sonar_scan.sh
```

### Against a local SonarQube server

```bash
docker run -d --name avd-sonar --hostname avdsonar --add-host avdsonar:127.0.0.1 \
  -p 9001:9000 -e SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true sonarqube:community
```

Wait for `http://localhost:9001/api/system/status` to report `UP`, generate a
token in the UI, then:

```bash
export SONAR_HOST_URL=http://localhost:9001
export SONAR_TOKEN=<local-token>
./tools/run_sonar_scan.sh -Dsonar.projectKey=Auto-VHS-Deinterlacer -Dsonar.organization=
```

The `-D` overrides are needed because `sonar.organization` and the
`ventura8_`-prefixed key are SonarQube Cloud concepts.

Set `AVD_SONAR_SKIP_TESTS=1` to reuse an existing `assets/coverage.xml` instead
of re-running the suite.
