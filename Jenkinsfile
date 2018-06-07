#!/usr/bin/env groovy
node {
  stage('Configure tailor-distro') {
    checkout scm
    sh 'ls -la'
  }
  stage('Pull source') {
    milestone(1)
    node {
      docker.image('ubuntu:bionic').inside {
        sh 'ls -la'
        sh 'apt-get update && apt-get install -qy python-pip'
        sh 'pip install .'
        sh './scripts/pull_distro'
      }
    }
    cleanWs()
  }



}
