# Jenkins Setup

This project expects the Jenkins build agent to provide the runtime tools used by the pipeline.

## Quick Start: Install to Running Jenkins Container

If you have Jenkins running in Docker, install Python and dependencies using `docker exec`:

```bash
# Find the Jenkins container
docker ps | grep jenkins

# Install Python and required tools (run as root)
docker exec -u root jenkins_pipe bash -c 'apt-get update && apt-get install -y python3 python3-pip python3-venv docker.io build-essential curl'

# Add jenkins user to docker group for Docker socket access
docker exec -u root jenkins_pipe usermod -aG docker jenkins

# Verify installation
docker exec jenkins_pipe python3 --version
docker exec jenkins_pipe pip3 --version
docker exec jenkins_pipe docker --version
```

**Note:** After adding the jenkins user to the docker group, Jenkins may need to be restarted or new build jobs will need to be triggered for the group membership to take effect.

## Required Agent Packages

On Debian or Ubuntu agents, install:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip docker.io build-essential curl git
sudo usermod -aG docker jenkins  # Add jenkins user to docker group
sudo systemctl restart jenkins   # Restart Jenkins for group changes to take effect
```

## Why These Packages Are Needed

- `python3` is required to create the virtual environment in the pipeline.
- `python3-venv` is required for `python3 -m venv .venv`.
- `python3-pip` is required to install project dependencies.
- `docker.io` is required for the Docker build and push stages.

## Jenkins Node Recommendation

Run this job on an agent labeled with both Python and Docker support, for example:

- `python-docker`

If you use a labeled node, update the Jenkinsfile agent to match that label or configure the multibranch project to target the appropriate node.

## Virtual Environment (PEP 668)

This Jenkins setup uses a **workspace-scoped virtual environment** (`.venv` directory) instead of installing packages globally. This complies with [PEP 668](https://peps.python.org/pep-0668/) which prevents directly installing packages via pip on Debian-based systems.

The pipeline stages:
1. Creates `.venv` in the workspace: `python3 -m venv .venv`
2. Installs requirements into the venv: `.venv/bin/pip install -r requirements.txt`
3. Runs all tools from within the venv: `.venv/bin/pytest`, etc.

This approach isolates project dependencies from the system Python and prevents conflicts with other projects.

## Validation

After provisioning the agent, verify the tools are available:

```bash
python3 --version
python3 -m venv --help
docker --version
git --version
```

Then trigger a new Jenkins build to test the complete pipeline.

## Docker Socket Access

If you see Docker permission errors during the build, ensure the jenkins user can access the Docker daemon socket. The jenkins user should be in the docker group:

```bash
# Check jenkins user groups
docker exec jenkins_pipe id jenkins

# Should show: groups=...102(docker)...

# If not in docker group, add it:
docker exec -u root jenkins_pipe usermod -aG docker jenkins

# Restart the Jenkins container for group changes to take effect
docker restart jenkins_pipe
```
