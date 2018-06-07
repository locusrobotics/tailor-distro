#!/usr/bin/env groovy
node {
  def environment = null

  stage('Configure environment') {
    dir('tailor-distro') {
      checkout(scm)
    }
    stash(name: "source", includes: 'tailor-distro/')
    environment = docker.build("environment", "tailor-distro/environment")
  }

  stage('Pull sources') {
    milestone(1)
    node {
      environment.inside {
        unstash(name: "source")
        sh 'pip3 install -e tailor-distro'
        sh 'pull_distro'
        stash(name: "workspace", includes: 'workspace/')
      }
    }
  }
}
