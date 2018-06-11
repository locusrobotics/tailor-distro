#!/usr/bin/env groovy

// Learn groovy: https://learnxinyminutes.com/docs/groovy/

node {
  def environment = [:]

  stage('Configure parent environment') {
    dir('tailor-distro') {
      checkout(scm)
    }
    environment["parent"] = docker.build("parent", "-f tailor-distro/environment/Dockerfile .")
  }

  stage('Pull distro sources') {
    milestone(1)
    node {
      environment["parent"].inside {
        sh 'pull_distro_repositories'
        stash(name: "workspace", includes: 'workspace/')
      }
    }
  }

  def bundle_name = "developer"

  stage('Build bundle') {
    milestone(2)
    node {
      environment["parent"].inside {
        unstash(name: "workspace")
        sh 'generate_bundle_templates'
      }
      sh 'ls -la'
      environment[bundle_name] = docker.build(bundle_name, "-f workspace/src/Dockerfile .")
      // environment["build-${bundle_name}"] = docker.build("environment", "tailor-distro/build")
      environment[bundle_name].inside {
        sh 'cd workspace/src && catkin build'
      }
      environment["parent"].inside {
      // TODO(pbovbel): make templated environment dockerfile for bundle build
      }
    }
  }
}
