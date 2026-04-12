# Jenkins Setup Guide (Step-by-Step)

This guide explains exactly how to configure Jenkins for this repository using the current CI-only pipeline in [Jenkinsfile](../Jenkinsfile).

The pipeline stages are:
1. Checkout
2. Install Dependencies
3. Run Tests (with JUnit report publishing)
4. Build Docker Image
5. Optional Push Docker Image (main branch only)

## 1. Prerequisites

Install or verify these tools on your machine:
1. Docker
2. Git
3. A Git hosting account for this repository (GitHub/GitLab/Bitbucket)

Verify locally:

```bash
docker --version
git --version
```

## 2. Start Jenkins in Docker

Run Jenkins as a container:

```bash
docker run -d --name jenkins \
  -p 8080:8080 -p 50000:50000 \
  -v jenkins_home:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  jenkins/jenkins:lts
```

Check Jenkins container status:

```bash
docker ps --filter name=jenkins
```

## 3. Get Initial Admin Password

Read Jenkins unlock password:

```bash
docker exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

## 4. Unlock Jenkins and Complete First Login

1. Open `http://localhost:8080`.
2. Paste the password from Step 3.
3. Click **Continue**.
4. Select **Install suggested plugins**.
5. Wait for plugin installation.
6. Create your admin user (recommended), or continue with admin.
7. Set Jenkins URL as `http://localhost:8080`.

## 5. Install Required Plugins

Go to **Manage Jenkins -> Plugins** and ensure these are installed:
1. Pipeline
2. Git
3. JUnit
4. Credentials Binding
5. Docker Pipeline
6. Git Branch Source (recommended for multibranch)

Optional plugins:
1. GitHub plugin
2. Blue Ocean

## 6. Add Jenkins Credentials (Only If Needed)

For CI-only (no push), this step is optional.

If you want optional Docker push from main branch, add Docker Hub credentials:
1. Go to **Manage Jenkins -> Credentials -> System -> Global credentials (unrestricted)**.
2. Click **Add Credentials**.
3. Kind: **Username with password**.
4. Username: Docker Hub username.
5. Password: Docker Hub password or access token.
6. ID: `dockerhub-credentials`.
7. Description: `Docker Hub credentials for image push`.
8. Save.

## 7. Create Jenkins Multibranch Pipeline Job

1. From Jenkins dashboard, click **New Item**.
2. Enter name: `fraud-detection-engine`.
3. Select **Multibranch Pipeline**.
4. Click **OK**.

### Configure Branch Source

1. In **Branch Sources**, click **Add source**.
2. Choose your Git provider (for example, GitHub).
3. Configure repository URL.
4. If private repo, select the proper credentials.

### Configure Build Discovery

1. Keep default branch discovery settings, or select all branches.
2. Leave script path as `Jenkinsfile`.
3. Save.

## 8. Scan Repository and Discover Branch Jobs

1. Open the new multibranch job.
2. Click **Scan Multibranch Pipeline Now**.
3. Jenkins creates branch jobs automatically.

## 9. Run a Build (CI-Only)

1. Open your target branch job.
2. Click **Build with Parameters**.
3. Set `ENABLE_DOCKER_PUSH=false`.
4. Click **Build**.

Expected behavior:
1. Checkout runs.
2. Dependencies are installed.
3. Tests run and generate `reports/test-results.xml`.
4. Docker image builds.
5. Push stage is skipped.

## 10. View Test Results in Jenkins UI (JUnit)

After the build finishes:
1. Open the build number.
2. Click **Test Result**.
3. You should see pytest case summary from `reports/test-results.xml`.

If missing, check:
1. `Run Tests` stage completed.
2. `reports/test-results.xml` exists.
3. Build logs for junit publishing output.

## 11. Optional: Enable Docker Push (main branch only)

This pipeline pushes only when both conditions are true:
1. Branch is `main`.
2. `ENABLE_DOCKER_PUSH=true`.

Steps:
1. Ensure `dockerhub-credentials` exists (Step 6).
2. Build `main` branch.
3. Set parameter `ENABLE_DOCKER_PUSH=true`.
4. Run build.

## 12. Local Validation Before Pushing Code

Run the same key CI checks locally:

```bash
python3 -m pip install -r requirements.txt
pytest tests/ -v --junitxml=reports/test-results.xml
docker build -f docker/Dockerfile -t fraud-detection-engine:local .
```

## 13. Recommended Job Settings

In your multibranch job, consider enabling:
1. Periodic scan (for branch discovery).
2. Build retention policy (discard old builds).
3. Concurrent build prevention (already in pipeline with `disableConcurrentBuilds()`).

## 14. Troubleshooting

### A) "docker: not found"
Cause: Docker CLI not available in Jenkins runtime.
Fix:
1. Ensure Jenkins container has access to Docker socket (`-v /var/run/docker.sock:/var/run/docker.sock`).
2. If using non-Docker Jenkins, install Docker on the Jenkins agent node.

### B) "permission denied" on Docker socket
Cause: Jenkins runtime user cannot access Docker daemon.
Fix:
1. Use a Jenkins agent with proper Docker permissions.
2. Validate with a simple `docker ps` in a shell step.

### C) Python or pip missing
Cause: Agent environment missing Python.
Fix:
1. Use an agent image/node with Python 3 installed.
2. Verify with `python3 --version` in a pre-check stage.

### D) Test Result page empty
Cause: JUnit XML not generated or wrong path.
Fix:
1. Confirm `pytest ... --junitxml=reports/test-results.xml` ran successfully.
2. Confirm `junit testResults: 'reports/test-results.xml'` path matches exactly.

### E) Push stage skipped unexpectedly
Cause: Gating condition not met.
Fix:
1. Check branch is exactly `main`.
2. Check `ENABLE_DOCKER_PUSH=true` for that build.

## 15. Quick Checklist

1. Jenkins container running
2. Jenkins unlocked and admin account created
3. Required plugins installed
4. Multibranch job created
5. Repository scanned
6. Build run with `ENABLE_DOCKER_PUSH=false`
7. Test results visible in Jenkins UI
8. Optional Docker push works on `main` with credentials
