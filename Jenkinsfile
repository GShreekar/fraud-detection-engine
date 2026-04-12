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

        stage('Run Tests') {
            steps {
                sh 'mkdir -p reports'
                sh 'docker run --rm -v "$PWD:/app" -w /app python:3.12-slim sh -lc "pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt && pytest tests/ -v --junitxml=reports/test-results.xml"'
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
