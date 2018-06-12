#!/usr/bin/env groovy

// Learn groovy: https://learnxinyminutes.com/docs/groovy/

node {
  try{
    def projectProperties = [
      [$class: 'BuildDiscarderProperty',strategy: [$class: 'LogRotator', numToKeepStr: '5']],
    ]

    def series = env.BRANCH_NAME
    if (series == 'master') {
      series = 'hotdog'
      projectProperties.add(pipelineTriggers([cron('H/30 * * * *')]))
    }

    def ros_distro = "locus"

    properties(projectProperties)

    def environment = [:]

    def parent_image = "${series}-parent"
    def workspace_stash = "${series}-workspace"

    stage("Build parent environment ${series}") {
      node {
        cleanWs()
        sh "env"
        if (env.TAG_NAME != null) {
          echo "${env.TAG_NAME}"
        }
        dir('tailor-distro') {
          checkout(scm)
        }
        environment[parent_image] = docker.build(parent_image, "-f tailor-distro/environment/Dockerfile .")
      }
    }

    stage("Pull distribution packages ${series}") {
      milestone(1)
      node {
        cleanWs()
        ws(dir: 'workspace/distro_package_cache') {
          environment[parent_image].inside {
            sh 'pull_distro_repositories'
            stash(name: workspace_stash, includes: 'workspace/src/')
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
    def flavour = "developer"

    def bundle_id = "${series}-${flavour}"
    def template_stash = "${bundle_id}-templates"
    def debian_stash = "${bundle_id}-debian"
    def bundle_image = "${bundle_id}-bundle"

    stage("Build bundle ${bundle_id} environment") {
      milestone(2)
      node {
        cleanWs()
        environment[parent_image].inside {
          unstash(name: workspace_stash)
          sh 'generate_bundle_templates'
          stash(name: template_stash, includes: 'workspace/src/debian/')
        }
        environment[bundle_image] = docker.build(bundle_image, '-f workspace/src/Dockerfile .')
      }
    }

    stage("Test bundle ${bundle_id}") {
      milestone(3)
      node {
        cleanWs()
        environment[bundle_image].inside('-v /tmp/ccache:/ccache') {
          unstash(name: workspace_stash)
          // sh 'cd workspace && catkin build && catkin run_tests && source install/setup.bash && catkin_test_results build'
          sh 'ls -la workspace/src'
        }
      }
    }

    stage("Package bundle ${bundle_id}") {
      milestone(4)
      node {
        cleanWs()
        environment[bundle_image].inside {
          unstash(name: workspace_stash)
          unstash(name: template_stash)
          sh 'cd workspace/src && dpkg-buildpackage -uc -us'
          stash(name: debian_stash, includes: "workspace/${flavour}*.deb")
        }
      }
    }

    stage("Ship bundle ${bundle_id}") {
      milestone(5)
      node {
        cleanWs()
        environment[parent_image].inside {
          unstash(name: debian_stash)
          sh 'ls -la workspace'
          // TODO(pbovbel) upload package to apt repo
        }
      }
    }
  }
  // catch(Exception exc) {
  //   TODO(pbovbel) error handling (email/slack/etc)
  // }
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
