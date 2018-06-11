#!/usr/bin/env groovy
node {
  def environment = [:]

  stage('Configure parent environment') {
    dir('tailor-distro') {
      checkout(scm)
    }
    stash(name: "source", includes: 'tailor-distro/')
    environment["parent"] = docker.build("parent", "-f tailor-distro/environment/Dockerfile .")
  }

  stage('Pull distro sources') {
    milestone(1)
    node {
      environment["parent"].inside {
        sh 'pull_distro'
        stash(name: "workspace", includes: 'workspace/')
      }
    }
  }

  def bundle_name = "bundle"

  stage('Build bundle') {
    milestone(2)
    node {
      environment["parent"].inside {
      // TODO(pbovbel): build templates for bundle build
      }
      // environment["build-${bundle_name}"] = docker.build("environment", "tailor-distro/build")
      // environment["build-${bundle_name}"].inside {
      //   // TODO(pbovbel): build debian package
      // }
      environment["parent"].inside {
      // TODO(pbovbel): make templated environment dockerfile for bundle build
      }
    }
  }
}
