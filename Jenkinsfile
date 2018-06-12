#!/usr/bin/env groovy

// Learn groovy: https://learnxinyminutes.com/docs/groovy/

node {
  try{
    def environment = [:]

    def parent = "parent"

    stage('Build parent environment') {
      dir('tailor-distro') {
        checkout(scm)
      }
      stash(name: "source", includes: 'tailor-distro/')
      environment[parent] = docker.build(parent, "-f tailor-distro/environment/Dockerfile .")
    }

    stage('Pull distribution packages') {
      milestone(1)
      node {
        environment[parent].inside {
          unstash(name: "source")
          sh 'pull_distro_repositories'
          stash(name: "workspace", includes: 'workspace/')
        }
      }
    }

    def bundle_name = "developer"

    stage('Build bundle environment') {
      milestone(2)
      node {
        environment[parent].inside {
          unstash(name: "workspace")
          sh 'generate_bundle_templates'
        }
        environment[bundle_name] = docker.build(bundle_name, "-f workspace/src/Dockerfile .")
      }
    }

    stage('Test bundle') {
      milestone(3)
      node {
        environment[bundle_name].inside {
          // sh 'cd workspace && catkin build'
        }
      }
    }

    stage('Package bundle') {
      milestone(4)
      node {
        environment[bundle_name].inside {
          sh 'cd workspace/src && dpkg-buildpackage -uc -us'
        }
      }
    }
  }
  finally {
    stage('Clean up docker') {
      sh 'docker system prune -f'
    }
  }

}
