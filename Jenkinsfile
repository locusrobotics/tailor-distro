#!/usr/bin/env groovy
def deploy = false

def docker_credentials = 'ecr:us-east-1:tailor_aws'

def recipes_config = 'rosdistro/config/recipes.yaml'
def upstream_config = 'rosdistro/config/upstream.yaml'
def rosdistro_index = 'rosdistro/rosdistro/index.yaml'
def workspace_dir = 'workspace'

def debian_version = new Date().format('yyyyMMdd.HHmmss')

def distributions = []
def recipes = [:]

def recipes_dir = workspace_dir + '/recipes'
def src_dir = workspace_dir + '/src'
def debian_dir = workspace_dir + '/debian'

def aptEndpoint = { release_track, bucket_name -> "s3:$bucket_name:$release_track/ubuntu/" }
def srcStash = { release -> release + '-src' }
def parentImage = { release, docker_registry -> docker_registry - "https://" + ':tailor-distro-' + release + '-parent-' + env.BRANCH_NAME }
def bundleImage = { recipe, docker_registry -> docker_registry - "https://" + ':tailor-distro-' + recipe + '-bundle-' + env.BRANCH_NAME }
def debianStash = { recipe -> recipe + "-debian"}
def packageStash = { recipe -> recipe + "-packages"}
def recipeStash = { recipe -> recipe + "-recipes"}

pipeline {
  agent none

  parameters {
    string(name: 'rosdistro_job', defaultValue: '/ci/rosdistro/master')
    string(name: 'release_track', defaultValue: 'hotdog')
    string(name: 'release_label', defaultValue: 'hotdog')
    string(name: 'num_to_keep', defaultValue: '10')
    string(name: 'days_to_keep', defaultValue: '10')
    string(name: 'docker_registry')
    string(name: 'apt_repo')
    booleanParam(name: 'deploy', defaultValue: false)
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

          properties([
            buildDiscarder(logRotator(
              daysToKeepStr: params.days_to_keep, numToKeepStr: params.num_to_keep,
              artifactDaysToKeepStr: params.days_to_keep, artifactNumToKeepStr: params.num_to_keep
            ))
          ])

          copyArtifacts(
            projectName: params.rosdistro_job,
            selector: upstream(fallbackToLastSuccessful: true),
          )
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
          def parent_image = docker.image(parentImage(params.release_label, params.docker_registry))
          try {
            docker.withRegistry(params.docker_registry, docker_credentials) { parent_image.pull() }
          } catch (all) {
            echo("Unable to pull ${parentImage(params.release_label, params.docker_registry)} as a build cache")
          }

          withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'tailor_aws']]) {
            unstash(name: 'rosdistro')
            parent_image = docker.build(parentImage(params.release_label, params.docker_registry),
              "-f tailor-distro/environment/Dockerfile --cache-from ${parentImage(params.release_label, params.docker_registry)} " +
              "--build-arg AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID " +
              "--build-arg AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY .")
          }
          parent_image.inside() {
            sh('cd tailor-distro && python3 setup.py test')
          }
          docker.withRegistry(params.docker_registry, docker_credentials) {
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
          def parent_image = docker.image(parentImage(params.release_label, params.docker_registry))
          docker.withRegistry(params.docker_registry, docker_credentials) { parent_image.pull() }

          parent_image.inside() {
            unstash(name: 'rosdistro')
            // Generate recipe configuration files
            def recipe_yaml = sh(
              script: "create_recipes --recipes $recipes_config --recipes-dir $recipes_dir " +
                      "--release-track $params.release_track --release-label $params.release_label --debian-version $debian_version",
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
                "--recipes $recipes_config  --rosdistro-index $rosdistro_index --clean"
              stash(name: srcStash(params.release_label), includes: "$src_dir/")
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


    stage("Create upstream mirrors") {
      agent none
      steps {
        script {
          def jobs = distributions.collectEntries { distribution ->
            [distribution, { node {
              try {
                def parent_image = docker.image(parentImage(params.release_label, params.docker_registry))
                docker.withRegistry(params.docker_registry, docker_credentials) {
                  parent_image.pull()
                }
                parent_image.inside("-v $HOME/tailor/gpg:/gpg") {
                  unstash(name: 'rosdistro')

                  sh("mirror_upstream $upstream_config --version $debian_version " +
                      "--endpoint ${aptEndpoint(params.release_track)} --distribution $distribution " +
                      "--keys /gpg/*.key ${params.deploy ? '--publish' : ''}")
                }
              } finally {
                  deleteDir()
                  // If two docker prunes run simulataneously, one will fail, hence || true
                  sh 'docker image prune -af --filter="until=3h" --filter="label=tailor" || true'
              }
            }}]
          }
          parallel(jobs)
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
                def parent_image = docker.image(parentImage(params.release_label, params.docker_registry))
                docker.withRegistry(params.docker_registry, docker_credentials) { parent_image.pull() }

                parent_image.inside() {
                  unstash(name: srcStash(params.release_label))
                  unstash(name: recipeStash(recipe_label))
                  sh "generate_bundle_templates --src-dir $src_dir --template-dir $debian_dir --recipe $recipe_path"
                  stash(name: debianStash(recipe_label), includes: "$debian_dir/")
                }

                def bundle_image = docker.image(bundleImage(recipe_label, params.docker_registry))
                try {
                  docker.withRegistry(params.docker_registry, docker_credentials) { bundle_image.pull() }
                } catch (all) {
                  echo "Unable to pull ${bundleImage(recipe_label, params.docker_registry)} as a build cache"
                }

                withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'tailor_aws']]) {
                  bundle_image = docker.build(bundleImage(recipe_label, params.docker_registry),
                    "-f $debian_dir/Dockerfile --cache-from ${bundleImage(recipe_label, params.docker_registry)} " +
                    "--build-arg AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID " +
                    "--build-arg AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY $workspace_dir")
                }

                docker.withRegistry(params.docker_registry, docker_credentials) { bundle_image.push() }

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

    stage("Build and package") {
      agent none
      steps {
        script {
          def jobs = recipes.collectEntries { recipe_label, recipe_path ->
            [recipe_label, { node {
              try {
                def bundle_image = docker.image(bundleImage(recipe_label, params.docker_registry))
                docker.withRegistry(params.docker_registry, docker_credentials) { bundle_image.pull() }

                bundle_image.inside("-v $HOME/tailor/ccache:/ccache") {
                  unstash(name: srcStash(params.release_label))
                  unstash(name: debianStash(recipe_label))
                  sh("""
                    ccache -z
                    cd $workspace_dir && dpkg-buildpackage -uc -us -b
                    ccache -s
                  """)
                  stash(name: packageStash(recipe_label), includes: "*.deb")
                }
              } finally {
                // Don't archive debs - too big. Consider s3 upload?
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
                def parent_image = docker.image(parentImage(params.release_label, params.docker_registry))
                docker.withRegistry(params.docker_registry, docker_credentials) { parent_image.pull() }

                parent_image.inside("-v $HOME/tailor/aptly:/aptly -v $HOME/tailor/gpg:/gpg") {
                  recipes.each { recipe_label, recipe_path ->
                    if (recipe_label.contains(distribution)) {
                      unstash(name: packageStash(recipe_label))
                    }
                  }
                  lock('aptly') {
                    unstash(name: 'rosdistro')
                    def origin = readYaml(file: recipes_config)['common']['origin']
                    if (params.deploy) {
                      sh("publish_packages *.deb --release-track $params.release_track " +
                         "--endpoint ${aptEndpoint(params.release_track)} " +
                         "--keys /gpg/*.key --distribution $distribution --origin $origin " +
                         "${params.days_to_keep != 'null' ? '--days-to-keep ' + params.days_to_keep : ''} " +
                         "${params.num_to_keep != 'null' ? '--num-to-keep ' + params.num_to_keep : ''}")
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
