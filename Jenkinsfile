#!/usr/bin/env groovy
node {
  def environment = null

  stage('Configure environment') {
    checkout scm
    environment = docker.build("environment", "environment")
  }

  stage('Pull sources') {
    milestone(1)
    node {
      environment.inside {
        checkout scm
        sh 'ls -la'
        sh 'pip3 install -e .'
        sh 'pull_distro'
      }
    }
  }

  cleanWs()
}
