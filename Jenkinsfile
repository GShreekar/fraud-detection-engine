pipeline {
    agent any

    parameters {
        booleanParam(
            name: 'ENABLE_DOCKER_PUSH',
            defaultValue: false,
            description: 'Push Docker image to registry (main branch only)'
        )
        string(
            name: 'DOCKER_REPOSITORY',
            defaultValue: 'gshreekar/fraud-detection-engine',
            description: 'Docker Hub repository in the format namespace/repo'
        )
    }

    environment {
        IMAGE_NAME = 'fraud-detection-engine'
        REGISTRY = 'docker.io'
        REGISTRY_REPO = "${REGISTRY}/${params.DOCKER_REPOSITORY}"
        DOCKER_CREDENTIALS_ID = 'dockerhub-credentials'
        HAS_DOCKER = 'false'
        PYTHON_BIN = ''
        UV_BIN = ''
    }

    options {
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Detect Docker') {
            steps {
                script {
                    env.HAS_DOCKER = sh(script: 'command -v docker >/dev/null 2>&1 && echo true || echo false', returnStdout: true).trim()
                    env.PYTHON_BIN = sh(
                        script: 'command -v python3 || command -v python || command -v python3.12 || true',
                        returnStdout: true
                    ).trim()
                    if (!env.PYTHON_BIN) {
                        env.UV_BIN = sh(
                            script: 'command -v uv || echo "$HOME/.local/bin/uv"',
                            returnStdout: true
                        ).trim()
                        if (!fileExists(env.UV_BIN)) {
                            if (sh(script: 'command -v curl >/dev/null 2>&1 && echo true || echo false', returnStdout: true).trim() == 'true') {
                                sh 'curl -LsSf https://astral.sh/uv/install.sh | sh'
                            }
                        }
                        if (!fileExists(env.UV_BIN)) {
                            error('No Python interpreter found and uv could not be bootstrapped on this Jenkins agent')
                        }
                        sh '"${UV_BIN}" python install 3.12'
                        env.PYTHON_BIN = sh(script: '"${UV_BIN}" python find 3.12', returnStdout: true).trim()
                    }
                    echo "Docker available: ${env.HAS_DOCKER}"
                    echo "Python interpreter: ${env.PYTHON_BIN}"
                }
            }
        }

        stage('Run Tests') {
            steps {
                sh 'mkdir -p reports'
                sh '"${PYTHON_BIN}" -m venv .venv'
                sh '.venv/bin/python -m pip install --upgrade pip'
                sh '.venv/bin/pip install -r requirements.txt'
                sh '.venv/bin/pytest tests/ -v --junitxml=reports/test-results.xml'
            }
            post {
                always {
                    junit allowEmptyResults: false, testResults: 'reports/test-results.xml'
                }
            }
        }

        stage('Build Docker Image') {
            when {
                expression { return env.HAS_DOCKER == 'true' }
            }
            steps {
                sh 'docker build -f docker/Dockerfile -t ${IMAGE_NAME}:${BUILD_NUMBER} .'
                sh 'docker tag ${IMAGE_NAME}:${BUILD_NUMBER} ${REGISTRY_REPO}:${BUILD_NUMBER}'
                sh 'docker tag ${IMAGE_NAME}:${BUILD_NUMBER} ${REGISTRY_REPO}:latest'
            }
        }

        stage('Push Docker Image (main only)') {
            when {
                allOf {
                    branch 'main'
                    expression { return params.ENABLE_DOCKER_PUSH }
                    expression { return env.HAS_DOCKER == 'true' }
                }
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
                    sh 'docker push ${REGISTRY_REPO}:${BUILD_NUMBER}'
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
