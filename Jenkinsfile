#!/usr/bin/env groovy

def debian_version = new Date().format('yyyyMMdd.HHmmss')

def deploy = false

def docker_registry = '084758475884.dkr.ecr.us-east-1.amazonaws.com/tailor-distro'
def docker_credentials = 'ecr:us-east-1:tailor_aws'
def apt_endpoint = 's3:tailor-packages:ubuntu/'

def recipes_config = 'rosdistro/config/recipes.yaml'
def workspace_dir = 'workspace'

def distributions = []
def recipes = [:]

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

  parameters {
    string(name: 'rosdistro_source', defaultValue: 'master')
    string(name: 'release_track', defaultValue: 'hotdog')
    string(name: 'release_label', defaultValue: 'hotdog')
    string(name: 'num_to_keep', defaultValue: '10')
    string(name: 'days_do_keep', defaultValue: '10')
  }

  options {
    timestamps()
  }

  stages {
    stage("Configure build parameters") {
      agent { label('master') }
      steps {
        script {
          sh('env')
          library("tailor-meta")
          cancelPreviousBuilds()

          // TODO(pbovbel) straighten out how this works
          deploy = env.BRANCH_NAME == 'master' ? true : false

          properties([
            buildDiscarder(logRotator(
              daysToKeepStr: params.days_do_keep, numToKeepStr: params.num_to_keep,
              artifactDaysToKeepStr: params.days_to_keep, artifactNumToKeepStr: params.num_to_keep
            ))
          ])

          copyArtifacts(projectName: "/ci/rosdistro/" + params.rosdistro_source)
          stash(name: 'rosdistro', includes: 'rosdistro/**')
        }
      }
      post {
        cleanup {
          deleteDir()
        }
      }
    }

    stage("Build and test tailor-distro") {
      agent any
      steps {
        script {
          dir('tailor-distro') {
            checkout(scm)
          }
          // stash(name: 'source', includes: 'tailor-mupstreameta/**')
          def parent_image = docker.image(parentImage(params.release_label))
          try {
            docker.withRegistry(docker_registry_uri, docker_credentials) { parent_image.pull() }
          } catch (all) {
            echo("Unable to pull ${parentImage(params.release_label)} as a build cache")
          }

          withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'tailor_aws']]) {
            parent_image = docker.build(parentImage(params.release_label),
              "-f tailor-distro/environment/Dockerfile --cache-from ${parentImage(params.release_label)} " +
              "--build-arg AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID " +
              "--build-arg AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY .")
          }
          parent_image.inside() {
            sh('cd tailor-distro && python3 setup.py test')
          }
          docker.withRegistry(docker_registry_uri, docker_credentials) {
            parent_image.push()
          }
        }
      }
      post {
        always {
          junit(testResults: 'tailor-distro/test-results.xml')
        }
        cleanup {
          deleteDir()
          // If two docker prunes run simultaneously, one will fail, hence || true
          sh('docker image prune -af --filter="until=3h" --filter="label=tailor" || true')
        }
      }
    }

    stage("Setup recipes and pull sources") {
      agent any
      steps {
        script {
          def parent_image = docker.image(parentImage(release_label))
          docker.withRegistry(docker_registry_uri, docker_credentials) { parent_image.pull() }

          parent_image.inside() {
            unstash(name: 'rosdistro')
            // Generate recipe configuration files
            def recipe_yaml = sh(
              script: "create_recipes --recipes $recipes_config --recipes-dir $recipes_dir " +
                      "--release-track $release_track --release-label $release_label --debian-version $debian_version",
              returnStdout: true).trim()

            // Script returns a mapping of recipe labels and paths
            recipes = readYaml(text: recipe_yaml)

            distributions = readYaml(file: recipes_config)['os'].collect {
              os, distribution -> distribution }.flatten()

            // Stash each recipe configuration individually for parallel build nodes
            recipes.each { recipe_label, recipe_path ->
              stash(name: recipeStash(recipe_label), includes: recipe_path)
            }

            // Pull down distribution sources
            withCredentials([string(credentialsId: 'tailor_github', variable: 'GITHUB_TOKEN')]) {
              sh "pull_distro_repositories --src-dir $src_dir --github-key $GITHUB_TOKEN " +
                "--recipes $recipes_config_path --clean"
              stash(name: srcStash(release_label), includes: "$src_dir/")
            }
          }
        }
      }
      post {
        always {
          archiveArtifacts(artifacts: "$recipes_dir/*.yaml")
        }
        cleanup {
          deleteDir()
          // If two docker prunes run simultaneously, one will fail, hence || true
          sh('docker image prune -af --filter="until=3h" --filter="label=tailor" || true')
        }
      }
    }

    stage("Create packaging environment") {
      agent none
      steps {
        script {
          def jobs = recipes.collectEntries { recipe_label, recipe_path ->
            [recipe_label, { node {
              try {
                def parent_image = docker.image(parentImage(release_label))
                docker.withRegistry(docker_registry_uri, docker_credentials) { parent_image.pull() }

                parent_image.inside() {
                  unstash(name: srcStash(release_label))
                  unstash(name: recipeStash(recipe_label))
                  sh "generate_bundle_templates --src-dir $src_dir --template-dir $debian_dir  --recipe $recipe_path"
                  stash(name: debianStash(recipe_label), includes: "$debian_dir/")
                }

                def bundle_image = docker.image(bundleImage(recipe_label))
                try {
                  docker.withRegistry(docker_registry_uri, docker_credentials) { bundle_image.pull() }
                } catch (all) {
                  echo "Unable to pull ${bundleImage(recipe_label)} as a build cache"
                }

                withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'tailor_aws']]) {
                  bundle_image = docker.build(bundleImage(recipe_label),
                    "-f $debian_dir/Dockerfile --cache-from ${bundleImage(recipe_label)} " +
                    "--build-arg AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID " +
                    "--build-arg AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY .")
                }

                docker.withRegistry(docker_registry_uri, docker_credentials) { bundle_image.push() }

              } finally {
                // Jenkins requires all artifacts to have unique filenames
                sh "find $debian_dir -type f -exec mv {} {}-$recipe_label \\; || true"
                archiveArtifacts(
                  artifacts: "$debian_dir/rules*, $debian_dir/control*, $debian_dir/Dockerfile*", allowEmptyArchive: true)
                deleteDir()
                sh 'docker image prune -af --filter="until=3h" --filter="label=tailor" || true'
              }
            }}]
          }
          parallel(jobs)
        }
      }
    }

    stage("Build and packag") {
      agent none
      steps {
        script {
          def jobs = recipes.collectEntries { recipe_label, recipe_path ->
            [recipe_label, { node {
              try {
                def bundle_image = docker.image(bundleImage(recipe_label))
                docker.withRegistry(docker_registry_uri, docker_credentials) { bundle_image.pull() }

                bundle_image.inside("-v $HOME/tailor/ccache:/ccache") {
                  unstash(name: srcStash(release_label))
                  unstash(name: debianStash(recipe_label))
                  sh("""
                    ccache -z
                    cd $workspace_dir && dpkg-buildpackage -uc -us -b
                    ccache -s
                  """)
                  stash(name: packageStash(recipe_label), includes: "*.deb")
                }
              } finally {
                // Don't archive debs - too big
                // archiveArtifacts(artifacts: "*.deb", allowEmptyArchive: true)
                deleteDir()
                sh 'docker image prune -af --filter="until=3h" --filter="label=tailor" || true'
              }
            }}]
          }
          parallel(jobs)
        }
      }
    }

    stage("Ship packages") {
      agent none
      steps {
        script {
          def jobs = distributions.collectEntries { distribution ->
            [distribution, { node('master') {
              try {
                def parent_image = docker.image(parentImage(release_label))
                docker.withRegistry(docker_registry_uri, docker_credentials) { parent_image.pull() }

                parent_image.inside("-v $HOME/tailor/aptly:/aptly -v $HOME/tailor/gpg:/gpg") {
                  recipes.each { recipe_label, recipe_path ->
                    if (recipe_label.contains(distribution)) {
                      unstash(name: packageStash(recipe_label))
                    }
                  }
                  lock('aptly') {
                    if (deploy) {
                      sh("publish_packages *.deb --release-track $release_track --endpoint $apt_endpoint --keys /gpg/*.key " +
                        "--distribution $distribution --days-to-keep $days_to_keep --num-to-keep $num_to_keep")
                    }
                  }
                }
              } finally {
                deleteDir()
                sh 'docker image prune -af --filter="until=3h" --filter="label=tailor" || true'
              }
            }}]
          }
          parallel(jobs)
        }
      }
    }
  }
}
