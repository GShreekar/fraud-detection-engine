pipeline {
    agent any

    parameters {
        choice(
            name: 'DEPLOY_ENV',
            choices: ['staging', 'production'],
            description: 'Target deployment environment'
        )
    }

    environment {
        IMAGE_NAME = "fraud-detection-engine"
        REGISTRY = "docker.io"
        REGISTRY_REPO = "${REGISTRY}/frauddetection/${IMAGE_NAME}"
        DOCKER_CREDENTIALS_ID = "dockerhub-credentials"
        SLACK_CHANNEL = "#fraud-engine-ci"
        DEPLOY_SSH_CREDENTIALS_ID = "deploy-ssh-credentials"
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
                setBuildStatus('pending', 'CI pipeline started')
            }
        }

        stage('Install Dependencies') {
            steps {
                sh 'pip install -r requirements.txt'
            }
        }

        stage('Run Tests') {
            steps {
                sh 'pytest tests/ -v --junitxml=reports/test-results.xml'
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'reports/test-results.xml'
                }
            }
        }

        stage('Build Docker Image') {
            steps {
                sh "docker build -f docker/Dockerfile -t ${IMAGE_NAME}:${BUILD_NUMBER} ."
                sh "docker tag ${IMAGE_NAME}:${BUILD_NUMBER} ${REGISTRY_REPO}:${BUILD_NUMBER}"
                sh "docker tag ${IMAGE_NAME}:${BUILD_NUMBER} ${REGISTRY_REPO}:latest"
            }
        }

        stage('Docker Login') {
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: "${DOCKER_CREDENTIALS_ID}",
                        usernameVariable: 'DOCKER_USER',
                        passwordVariable: 'DOCKER_PASS'
                    )
                ]) {
                    sh 'echo "$DOCKER_PASS" | docker login ${REGISTRY} -u "$DOCKER_USER" --password-stdin'
                }
            }
        }

        stage('Push Docker Image') {
            steps {
                sh "docker push ${REGISTRY_REPO}:${BUILD_NUMBER}"
                sh "docker push ${REGISTRY_REPO}:latest"
            }
        }

        stage('Deploy') {
            when {
                branch 'main'
            }
            steps {
                script {
                    def targetHost = (params.DEPLOY_ENV == 'production')
                        ? env.PRODUCTION_HOST
                        : env.STAGING_HOST

                    sshagent(credentials: ["${DEPLOY_SSH_CREDENTIALS_ID}"]) {
                        sh """
                            ssh -o StrictHostKeyChecking=no deployer@${targetHost} << 'ENDSSH'
                                docker pull ${REGISTRY_REPO}:${BUILD_NUMBER}
                                docker stop ${IMAGE_NAME} || true
                                docker rm ${IMAGE_NAME} || true
                                docker run -d \
                                    --name ${IMAGE_NAME} \
                                    --restart unless-stopped \
                                    -p 8000:8000 \
                                    --env-file /opt/${IMAGE_NAME}/.env.${params.DEPLOY_ENV} \
                                    ${REGISTRY_REPO}:${BUILD_NUMBER}
ENDSSH
                        """
                    }
                }
            }
        }
    }

    post {
        success {
            setBuildStatus('success', 'CI pipeline passed')
            echo "Pipeline succeeded — image pushed as ${REGISTRY_REPO}:${BUILD_NUMBER}"
        }
        failure {
            setBuildStatus('failure', 'CI pipeline failed')
            emailext(
                subject: "FAILED: ${env.JOB_NAME} #${env.BUILD_NUMBER}",
                body: """Build ${env.BUILD_URL} failed on branch ${env.BRANCH_NAME}.
                         |Check the console output for details.""".stripMargin(),
                to: 'team@frauddetection.dev',
                attachLog: true
            )
            slackSend(
                channel: "${SLACK_CHANNEL}",
                color: 'danger',
                message: ":x: *${env.JOB_NAME}* #${env.BUILD_NUMBER} failed on `${env.BRANCH_NAME}`.\n<${env.BUILD_URL}|View Build>"
            )
        }
        always {
            sh "docker logout ${REGISTRY} || true"
            cleanWs()
        }
    }
}

void setBuildStatus(String state, String description) {
    def context = 'ci/jenkins/pipeline'
    step([
        $class: 'GitHubCommitStatusSetter',
        reposSource: [$class: 'ManuallyEnteredRepositorySource', url: env.GIT_URL],
        contextSource: [$class: 'ManuallyEnteredCommitContextSource', context: context],
        statusResultSource: [
            $class: 'ConditionalStatusResultSource',
            results: [[$class: 'AnyBuildResult', state: state, message: description]]
        ]
    ])
}
