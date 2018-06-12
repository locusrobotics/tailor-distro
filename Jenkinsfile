#!/usr/bin/env groovy

// Learn groovy: https://learnxinyminutes.com/docs/groovy/

node {
  try{
    def projectProperties = [
      [$class: 'BuildDiscarderProperty',strategy: [$class: 'LogRotator', numToKeepStr: '5']],
    ]

    def series = null
    def date_version = new Date().format('yy.MM.dd')
    // def ros_distro = 'locus'

    // Create tagged release
    if (env.TAG_NAME != null) {
      series = env.TAG_NAME
      version = 'final'
    }
    // Create a release sausage
    else if (env.BRANCH_NAME == 'master') {
      series = 'hotdog'
      version = date_version
      projectProperties.add(pipelineTriggers([cron('H/30 * * * *')]))
    }
    // TODO(pbovbel release candidates
    // else if (env.BRANCH_NAME.startsWith('rc/')) {
    //   series = 'release'
    //   version = env.BRANCH_NAME
    // }
    // Create a 'feature' release
    else {
      series = env.BRANCH_NAME
      version = date_version
    }

    properties(projectProperties)

    def environment = [:]

    def parent_image = "${series}-parent"
    def workspace_stash = "${series}-workspace"

    stage("Configure ${series}") {
      node {
        cleanWs()
        sh "env"
        // if (env.TAG_NAME != null) {
        //   echo "${env.TAG_NAME}"
        // }
        dir('tailor-distro') {
          checkout(scm)
        }
        environment[parent_image] = docker.build(parent_image, "-f tailor-distro/environment/Dockerfile .")
      }
    }

    workspace_dir = 'catkin_ws'

    stage("Pull packages ${series}") {
      milestone(1)
      node {
        cleanWs()
        ws(dir: 'workspace/distro_package_cache') {
          environment[parent_image].inside {
            withCredentials([string(credentialsId: 'd32df494-e717-4416-8431-c1e10c0b90c4', variable: 'github_key')]) {
              sh "pull_distro_repositories --workspace-dir ${workspace_dir} --github-key ${github_key}"
              stash(name: workspace_stash, includes: 'workspace/src/')
            }
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

    def bundle_id = "${flavour}-${series}"
    def template_stash = "${bundle_id}-templates"
    def debian_stash = "${bundle_id}-debian"
    def bundle_image = "${bundle_id}-bundle"

    stage("Environment ${bundle_id}") {
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

    stage("Test ${bundle_id}") {
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

    stage("Package ${bundle_id}") {
      milestone(4)
      node {
        cleanWs()
        environment[bundle_image].inside('-v /tmp/ccache:/ccache') {
          unstash(name: workspace_stash)
          unstash(name: template_stash)
          sh 'ccache -z'
          sh 'cd workspace/src && dpkg-buildpackage -uc -us'
          sh 'ccache -s'  // show ccache stats after build
          stash(name: debian_stash, includes: "workspace/${flavour}*.deb")
        }
      }
    }

    stage("Ship ${bundle_id}") {
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
