#!/usr/bin/env groovy

// Learn groovy: https://learnxinyminutes.com/docs/groovy/

node {
  try{
    def environment = [:]

    def parent = "parent"
    def workspace = "workspace"

    stage("Build parent environment") {
      node {
        cleanWs()
        sh "env"
        dir('tailor-distro') {
          checkout(scm)
        }
        stash(name: "source", includes: 'tailor-distro/')
        environment[parent] = docker.build(parent, "-f tailor-distro/environment/Dockerfile .")
      }
    }

    stage("Pull distribution packages") {
      milestone(1)
      node {
        cleanWs()
        ws(dir: 'workspace/distro_package_cache') {
          environment[parent].inside {
            sh 'pull_distro_repositories'
            stash(name: "workspace", includes: 'workspace/src/')
          }
        },
        'System Tests' : {
          stage('System Tests') {
            node {
              ws {
                docker.image('ubuntu:bionic').inside {
                  echo "System Tests"
                  sh 'env'
                  unstash name: "mystash"
                  sh 'touch asdf/stage1d'
                  sh 'ls -la asdf'
                  cleanWs()
                }
              }
            }
          }
        }
      )
    }

    // TODO(pbovbel) create bundle matrix
    def bundle_name = "developer"
    def bundle_templates = "${bundle_name}_templates"
    def bundle_deb = "${bundle_name}_deb"

    stage("Build bundle ${bundle_name} environment") {
      milestone(2)
      node {
        cleanWs()
        environment[parent].inside {
          unstash(name: "workspace")
          sh 'generate_bundle_templates'
          stash(name: bundle_templates, includes: 'workspace/src/debian/')
        }
        environment[bundle_name] = docker.build(bundle_name, "-f workspace/src/Dockerfile .")
      }
    }

    stage("Test bundle ${bundle_name}") {
      milestone(3)
      node {
        cleanWs()
        environment[bundle_name].inside('-v /tmp/ccache:/ccache') {
          unstash(name: workspace)
          // sh 'cd workspace && catkin build && catkin run_tests && source install/setup.bash && catkin_test_results build'
          sh 'ls -la workspace/src'
        }
      }
    }

    stage("Package bundle ${bundle_name}") {
      milestone(4)
      node {
        cleanWs()
        environment[bundle_name].inside {
          unstash(name: workspace)
          unstash(name: bundle_templates)
          sh 'cd workspace/src && dpkg-buildpackage -uc -us'
          stash(name: bundle_deb, includes: "workspace/${bundle_name}*.deb")
        }
      }
    }

    stage("Ship bundle ${bundle_name}") {
      milestone(5)
      node {
        cleanWs()
        environment[parent].inside {
          unstash(name: bundle_deb)
          sh 'ls -la workspace'
          // TODO(pbovbel) upload package to apt repo
        }
      }
    }
  }
  finally {
    stage('Clean up docker') {
      sh 'docker system prune -f'
    }
  }
  finally {
    stage('Clean up docker') {
      sh 'docker system prune -f'
    }
  }

}
