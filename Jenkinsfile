#!/usr/bin/env groovy

// Learn groovy: https://learnxinyminutes.com/docs/groovy/

def release_track = 'hotdog'
def release_label = release_track
def debian_version = new Date().format('yyyyMMdd.HHmmss')

def days_to_keep = 30
def num_to_keep = 30
def build_schedule = null

def docker_registry = '084758475884.dkr.ecr.us-east-1.amazonaws.com/tailor'
def docker_credentials = 'ecr:us-east-1:tailor_aws'
def recipes_config_path = 'tailor-distro/rosdistro/recipes.yaml'
def workspace_dir = 'workspace'

def recipes = [:]
def environment = [:]
def parallel_environment = [:]
def parallel_bundle = [:]

def docker_registry_uri = 'https://' + docker_registry
def recipes_dir = workspace_dir + '/recipes'
def src_dir = workspace_dir + '/src'
def debian_dir = workspace_dir + '/debian'

def srcStash = { release -> release + '-src' }
def parentImage = { release -> docker_registry + ':jenkins-' + release + '-parent' }
def bundleImage = { recipe -> docker_registry + ':jenkins-' + recipe + "-bundle"}
def debianStash = { recipe -> recipe + "-debian"}
def packageStash = { recipe -> recipe + "-packages"}
def recipeStash = { recipe -> recipe + "-recipes"}

pipeline {
  agent none

  stages {
    stage("Configure build parameters") {
      agent any
      steps {
        script {
          cancelPreviousBuilds()

          // Choose build type based on tag/branch name
          if (env.TAG_NAME != null) {
            // Create tagged release
            release_track = env.TAG_NAME
            release_label = release_track + '-final'
            days_to_keep = null
          }
          else if (env.BRANCH_NAME.startsWith('release/')) {
            // Create a release candidate
            release_track = env.BRANCH_NAME - 'release/'
            release_label = release_track + '-rc'
            days_to_keep = null
          }
          else if (env.BRANCH_NAME == 'master') {
            // Create mystery meat package
            build_schedule = 'H/60 * * * *'
          }
          else {
            // Create a feature package
            release_label = release_track + '-' + env.BRANCH_NAME
          }
          release_track = release_track.replaceAll("\\.", '-')
          release_label = release_label.replaceAll("\\.", '-')

          // TODO(pbovbel) clean these up
          def projectProperties = [
            [$class: 'BuildDiscarderProperty',
              strategy: [$class: 'LogRotator', artifactDaysToKeepStr: days_to_keep.toString(),
                artifactNumToKeepStr: num_to_keep.toString(), daysToKeepStr: days_to_keep.toString(),
                numToKeepStr: num_to_keep.toString()]],
          ]
          if (build_schedule) {
            projectProperties.add(pipelineTriggers([cron(build_schedule)]))
          }
          properties(projectProperties)
        }
      }
    }

    stage("Pull down distribution") {
      agent any
      steps {
        script {
          dir('tailor-distro') {
            checkout(scm)
          }
          withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'tailor_aws']]) {
            environment[parentImage(release_label)] = docker.build(parentImage(release_label), "-f tailor-distro/environment/Dockerfile " +
              "--build-arg AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID " +
              "--build-arg AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY .")
          }
          docker.withRegistry(docker_registry_uri, docker_credentials) {
            environment[parentImage(release_label)].push()
          }

          environment[parentImage(release_label)].inside() {
            sh 'cd tailor-distro && python3 setup.py test'
            def recipe_yaml = sh(
              script: "create_recipes --recipes $recipes_config_path --recipes-dir $recipes_dir " +
                "--release-label $release_label --debian-version $debian_version",
              returnStdout: true).trim()
            recipes = readYaml(text: recipe_yaml)

            recipes.each { recipe_label, recipe_path ->
              stash(name: recipeStash(recipe_label), includes: recipe_path)
            }

            withCredentials([string(credentialsId: 'tailor_github', variable: 'GITHUB_TOKEN')]) {
              // TODO(pbovbel) consider caching git using https://www.npmjs.com/package/git-cache-http-server
              sh "pull_distro_repositories --src-dir $src_dir --github-key $GITHUB_TOKEN " +
                "--recipes $recipes_config_path"
              stash(name: srcStash(release_label), includes: "$src_dir/")
            }
          }
        }
      }
      post {
        always {
          script{
            junit(testResults: 'tailor-distro/test-results.xml', allowEmptyResults: true)
            archiveArtifacts(artifacts: "$recipes_dir/*.yaml", allowEmptyArchive: true)
            archiveArtifacts(artifacts: "**/*.repos", allowEmptyArchive: true)
          }
        }
        cleanup {
          script{
            deleteDir()
            // If two docker prunes run simulataneously, one will fail, hence || true
            sh 'docker image prune -af --filter="until=1h" --filter="label=tailor" || true'
          }
        }
      }
    }

    stage('Generate parallel jobs') {
      agent any
      steps {
        script {
          parallel_environment = recipes.collectEntries { recipe_label, recipe_path ->
            [recipe_label, {
              node {
                try {
                  docker.withRegistry(docker_registry_uri, docker_credentials) {
                    environment[parentImage(release_label)].pull()
                  }
                  environment[parentImage(release_label)].inside() {
                    unstash(name: srcStash(release_label))
                    unstash(name: recipeStash(recipe_label))
                    sh "generate_bundle_templates --src-dir $src_dir --template-dir $debian_dir  --recipe $recipe_path"
                    stash(name: debianStash(recipe_label), includes: "$debian_dir/")
                  }
                  environment[bundleImage(recipe_label)] =
                    docker.build(bundleImage(recipe_label), "-f $debian_dir/Dockerfile .")
                  docker.withRegistry(docker_registry_uri, docker_credentials) {
                    environment[bundleImage(recipe_label)].push()
                  }
                }
                finally {
                  // Jenkins requires all artifacts to have unique filenames
                  sh "find $debian_dir -type f -exec mv {} {}-$recipe_label \\; || true"
                  archiveArtifacts(
                    artifacts: "$debian_dir/rules*, $debian_dir/control*, $debian_dir/Dockerfile*", allowEmptyArchive: true)
                  deleteDir()
                  sh 'docker image prune -af --filter="until=1h" --filter="label=tailor" || true'
                }
              }
            }]
          }

          parallel_bundle = recipes.collectEntries { recipe_label, recipe_path ->
            [recipe_label, { node {
              try {
                docker.withRegistry(docker_registry_uri, docker_credentials) {
                  environment[bundleImage(recipe_label)].pull()
                }
                environment[bundleImage(recipe_label)].inside("-v $HOME/tailor/ccache:/ccache") {
                  unstash(name: srcStash(release_label))
                  unstash(name: debianStash(recipe_label))
                  sh 'ccache -z'
                  sh "cd $workspace_dir && dpkg-buildpackage -uc -us -b"
                  sh 'ccache -s'  // show ccache stats after build
                  stash(name: packageStash(recipe_label), includes: "*.deb")
                }
              }
              finally {
                archiveArtifacts(artifacts: "*.deb", allowEmptyArchive: true)
                deleteDir()
                sh 'docker image prune -af --filter="until=1h" --filter="label=tailor" || true'
              }
            }}]
          }
        }
      }
    }

    stage('Create packaging environments') {
      agent none
      steps {
        script {
          parallel parallel_environment
        }
      }
    }

    stage("Bundle packages") {
      agent none
      steps {
        script {
          parallel parallel_bundle
        }
      }
    }

    stage("Ship packages") {
      agent any
      steps {
        script {
          docker.withRegistry(docker_registry_uri, docker_credentials) {
            environment[parentImage(release_label)].pull()
          }
          environment[parentImage(release_label)].inside("-v $HOME/tailor/aptly:/aptly -v $HOME/tailor/gpg:/gpg") {
            recipes.each { recipe_label, recipe_path ->
              unstash(name: packageStash(recipe_label))
            }
            lock('aptly') {
              sh("publish_packages *.deb --release-track $release_track --endpoint s3:tailor-packages: " +
                "--keys /gpg/*.key --days-to-keep $days_to_keep --num-to-keep $num_to_keep")
            }
          }
        }
      }
      post {
        cleanup {
          script {
            deleteDir()
            sh 'docker image prune -af --filter="until=1h" --filter="label=tailor" || true'
          }
        }
      }
    }

  }
}

@NonCPS
def cancelPreviousBuilds() {
    def jobName = env.JOB_NAME
    def buildNumber = env.BUILD_NUMBER.toInteger()
    /* Get job name */
    def currentJob = Jenkins.instance.getItemByFullName(jobName)

    /* Iterating over the builds for specific job */
    for (def build : currentJob.builds) {
        /* If there is a build that is currently running and it's older than current build */
        if (build.isBuilding() && build.number.toInteger() < buildNumber) {
            /* Than stopping it */
            build.doStop()
        }
    }
}
