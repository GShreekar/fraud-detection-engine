pipeline {
    agent any

    parameters {
        booleanParam(
            name: 'ENABLE_DOCKER_PUSH',
            defaultValue: false,
            description: 'Push Docker image to registry (main branch only)'
        )
    }

    environment {
        IMAGE_NAME = 'fraud-detection-engine'
        REGISTRY = 'docker.io'
        REGISTRY_REPO = "${REGISTRY}/frauddetection/${IMAGE_NAME}"
        DOCKER_CREDENTIALS_ID = 'dockerhub-credentials'
        PYTHON_DOCKER_IMAGE = 'python:3.12-slim'
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

        stage('Install Dependencies') {
            steps {
                sh 'docker run --rm -v "$PWD":/workspace -w /workspace ${PYTHON_DOCKER_IMAGE} sh -lc "python -m pip install --upgrade pip && python -m pip install -r requirements.txt"'
            }
        }

        stage('Run Tests') {
            steps {
                sh 'mkdir -p reports'
                sh 'docker run --rm -v "$PWD":/workspace -w /workspace ${PYTHON_DOCKER_IMAGE} sh -lc "python -m pip install --upgrade pip && python -m pip install -r requirements.txt && pytest tests/ -v --junitxml=reports/test-results.xml"'
            }
            post {
                always {
                    junit allowEmptyResults: false, testResults: 'reports/test-results.xml'
                }
            }
        }

        stage('Build Docker Image') {
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
