#!/usr/bin/env groovy

// Learn groovy: https://learnxinyminutes.com/docs/groovy/

node {
  try{
    sh "env"

    def projectProperties = [
      [$class: 'BuildDiscarderProperty',strategy: [$class: 'LogRotator', numToKeepStr: '5']],
    ]

    def series = null
    def version = new Date().format('yyyyMMdd.HHmmss')

    // Create tagged release
    if (env.TAG_NAME != null) {
      series = env.TAG_NAME
    }
    // Create a release sausage
    else if (env.BRANCH_NAME == 'master') {
      series = 'hotdog'
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
    }

    properties(projectProperties)

    def environment = [:]
    def parent_image = series + '-parent'
    def workspace_dir = 'catkin_ws/'
    def recipes = [:]
    def recipes_dir = workspace_dir + 'recipes/'
    // def flavour_stash = "${series}-flavours"
    def src_dir = workspace_dir + 'src/'
    def src_stash = series + '-src'
    def debian_dir = workspace_dir + 'debian/'

    stage("Configure distribution") {
      node {
        milestone(1)
        cleanWs()
        dir('tailor-distro') {
          checkout(scm)
        }
        environment[parent_image] = docker.build(parent_image, "-f tailor-distro/environment/Dockerfile .")
        environment[parent_image].inside {
          def recipe_yaml = sh(script: "create_recipes --recipes tailor-distro/rosdistro/recipes.yaml " +
            "--recipes-dir ${recipes_dir} --series ${series} --version ${version}", returnStdout: true).trim()
          recipes = readYaml(text: recipe_yaml)

          recipes.each { recipe_name, recipe_path ->
            stash(name: recipe_name, includes: recipe_path)
          }

        }
      }
    }

    stage("Pull packages") {
      milestone(2)
      node {
        cleanWs()
        lock('distro_package_cache') {
          ws(dir: "$WORKSPACE/../distro_package_cache") {
            environment[parent_image].inside {
              withCredentials([string(credentialsId: 'd32df494-e717-4416-8431-c1e10c0b90c4', variable: 'github_key')]) {
                sh "pull_distro_repositories --src-dir ${src_dir} --github-key ${github_key}"
                stash(name: src_stash, includes: src_dir)
              }
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

    def bundleImage = { recipe_name -> recipe_name + "-bundle"}
    def debianStash = { recipe_name -> recipe_name + "-debian"}
    def packageStash = { recipe_name -> recipe_name + "-packages"}

    stage('Build environment') {
      milestone(3)

      def environment_jobs = recipes.collectEntries { recipe_name, recipe_path ->
        [recipe_name : node {
          cleanWs()
          environment[parent_image].inside {
            unstash(name: src_stash)
            unstash(name: recipe_name)
            sh "generate_bundle_templates --workspace-dir ${workspace_dir} --recipe ${recipe_path}"
            stash(name: debianStash(recipe_name), includes: debian_dir)
          }
          environment[bundleImage(recipe_name)] = docker.build(bundleImage(recipe_name), "-f ${workspace_dir}/Dockerfile .")
        }]
      }
      parallel environment_jobs
      sh 'false'
    }

    stage("Test bundle") {
      milestone(4)
      node {
        cleanWs()
        environment[bundleImage(recipe_name)].inside('-v /tmp/ccache:/ccache') {
          unstash(name: src_stash)
          // sh 'cd workspace && catkin build && catkin run_tests && source install/setup.bash && catkin_test_results build'
          sh "ls -la ${workspace_dir}"
        }
      }
    }

    stage("Package bundle") {
      milestone(5)
      node {
        cleanWs()
        environment[bundleImage(recipe_name)].inside('-v /tmp/ccache:/ccache') {
          unstash(name: src_stash)
          unstash(name: debianStash(recipe_name))
          sh 'ccache -z'
          sh "cd ${workspace_dir} && dpkg-buildpackage -uc -us"
          sh 'ccache -s'  // show ccache stats after build
          stash(name: packageStash(recipe_name), includes: "*.deb")
        }
      }
    }

    stage("Ship bundle") {
      milestone(6)
      node {
        cleanWs()
        environment[parent_image].inside {
          unstash(name: packageStash(recipe_name))
          sh "ls -la *.deb"
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

// Required due to JENKINS-27421
@NonCPS
List<List<?>> mapToList(Map map) {
  return map.collect { it ->
    [it.key, it.value]
  }
}
