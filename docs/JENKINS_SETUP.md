# Jenkins Setup

This project expects the Jenkins build agent to provide the runtime tools used by the pipeline.

## Required Agent Packages

On Debian or Ubuntu agents, install:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip docker.io
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

## Validation

After provisioning the agent, verify the tools are available:

```bash
python3 --version
python3 -m venv --help
docker --version
```

Then rerun the Jenkins job.
