#!/usr/bin/env groovy
node {
  stage('Configure tailor-distro') {
    checkout scm
    def environment = docker.build("environment", "environment")
  }
  stage('Pull source') {
    milestone(1)
    node {
      environment.image('ubuntu:bionic').inside {
        sh 'pip install .'
        sh './scripts/pull_distro'
      }
    }
    cleanWs()
  }



}
