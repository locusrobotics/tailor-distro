#!/usr/bin/env groovy
node {
  stage('Configure tailor-distro') {
    checkout scm
  }
  stage('Pull source') {
    milestone(1)
    node {
      def environment = docker.build("environment", "environment")
      environment.image('ubuntu:bionic').inside {
        sh 'pip install .'
        sh './scripts/pull_distro'
      }
    }
    cleanWs()
  }



}
