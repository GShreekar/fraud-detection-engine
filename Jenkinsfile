pipeline {
    agent any

    triggers {
        pollSCM('* * * * *')  // Poll GitHub every minute for changes
    }

    environment {
        IMAGE_NAME = 'fraud-detection-engine'
        REGISTRY = 'docker.io'
        REGISTRY_REPO = "${REGISTRY}/gshreekar/${IMAGE_NAME}"
        DOCKER_CREDENTIALS_ID = 'dockerhub-credentials'
    }

    options {
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    stages {
        stage('Ensure Python Runtime') {
            steps {
                sh '''
                    set -e

                    if command -v python3 >/dev/null 2>&1; then
                        echo "python3 already available: $(python3 --version)"
                        exit 0
                    fi

                    echo "python3 not found. Attempting automatic installation..."

                    if command -v apt-get >/dev/null 2>&1; then
                        if [ "$(id -u)" -eq 0 ]; then
                            apt-get update
                            apt-get install -y --no-install-recommends python3 python3-venv python3-pip
                            rm -rf /var/lib/apt/lists/*
                        elif command -v sudo >/dev/null 2>&1; then
                            sudo apt-get update
                            sudo apt-get install -y --no-install-recommends python3 python3-venv python3-pip
                            sudo rm -rf /var/lib/apt/lists/*
                        else
                            echo "python3 is missing and this agent lacks privileges to install it."
                            exit 1
                        fi
                    else
                        echo "python3 is missing and apt-get is unavailable on this agent."
                        exit 1
                    fi

                    python3 --version
                '''
            }
        }

        stage('Install Dependencies') {
            steps {
                sh 'python3 -m venv .venv'
                sh '.venv/bin/python -m pip install --upgrade pip'
                sh '.venv/bin/pip install -r requirements.txt'
            }
        }

        stage('Run Tests') {
            steps {
                sh 'mkdir -p reports'
                sh '.venv/bin/pytest tests/ -v --junitxml=reports/test-results.xml'
            }
            post {
                always {
                    junit allowEmptyResults: false, testResults: 'reports/test-results.xml'
                }
            }
        }

        stage('Build Docker Image') {
            steps {
                sh 'docker build -f docker/Dockerfile -t ${REGISTRY_REPO}:latest .'
            }
        }

        stage('Push Docker Image') {
            when {
                expression { env.GIT_BRANCH == 'origin/main' || env.GIT_BRANCH == 'main' }
            }
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: "${DOCKER_CREDENTIALS_ID}",
                        usernameVariable: 'DOCKER_USER',
                        passwordVariable: 'DOCKER_PASS'
                    )
                ]) {
                    sh 'echo "$DOCKER_PASS" | docker login ${REGISTRY} -u "$DOCKER_USER" --password-stdin'
                    sh 'docker push ${REGISTRY_REPO}:latest'
                }
            }
            post {
                always {
                    sh 'docker logout ${REGISTRY} || true'
                }
            }
        }
    }

    post {
        success {
            echo 'CI pipeline passed.'
        }
        failure {
            echo 'CI pipeline failed. Check stage logs and test report.'
        }
    }
}
