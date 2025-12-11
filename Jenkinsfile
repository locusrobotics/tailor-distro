#!/usr/bin/env groovy
def deploy = false

def docker_credentials = 'ecr:us-east-1:tailor_aws'

def recipes_yaml = 'rosdistro/config/recipes.yaml'
def upstream_yaml = 'rosdistro/config/upstream.yaml'
def rosdistro_index = 'rosdistro/rosdistro/index.yaml'
def workspace_dir = 'workspace'

def distributions = []
def recipes = [:]

def recipes_dir = workspace_dir + '/recipes'
def src_dir = workspace_dir + '/src'
def debian_dir = workspace_dir + '/debian'

def srcStash = { release -> release + '-src' }
def parentImage = { release, docker_registry -> docker_registry - "https://" + ':tailor-distro-' + release + '-parent-' + env.BRANCH_NAME }
def bundleImage = { release, os_version, docker_registry -> docker_registry - "https://" + ':tailor-distro-' + release + '-bundle-' + os_version + '-' + env.BRANCH_NAME }
def debianStash = { recipe -> recipe + "-debian"}
def packageStash = { recipe -> recipe + "-packages"}
def recipeStash = { recipe -> recipe + "-recipes"}

pipeline {
  agent none

  parameters {
    string(name: 'rosdistro_job', defaultValue: '/ci/toydistro/master')
    string(name: 'release_track', defaultValue: 'hotdog')
    string(name: 'release_label', defaultValue: 'hotdog')
    string(name: 'num_to_keep', defaultValue: '10')
    string(name: 'days_to_keep', defaultValue: '10')
    string(name: 'timestamp')
    string(name: 'python_version', defaultValue: '3')
    string(name: 'tailor_meta')
    string(name: 'docker_registry')
    string(name: 'apt_repo')
    string(name: 'retries', defaultValue: '3')
    booleanParam(name: 'deploy', defaultValue: false)
    booleanParam(name: 'force_mirror', defaultValue: false)
    booleanParam(name: 'invalidate_cache', defaultValue: false)
    string(name: 'apt_refresh_key')
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
          def parent_image_label = parentImage(params.release_label, params.docker_registry)
          def parent_image = docker.image(parent_image_label)

          withEnv(['DOCKER_BUILDKIT=1']) {
            try {
              docker.withRegistry(params.docker_registry, docker_credentials) {parent_image.pull()}
            } catch (all) {
              echo("Unable to pull ${parent_image_label} as a build cache")
            }

            withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'tailor_aws']]) {
              unstash(name: 'rosdistro')
              parent_image = docker.build(parent_image_label,
                "${params.invalidate_cache ? '--no-cache ' : ''}" +
                "-f tailor-distro/environment/Dockerfile --cache-from ${parent_image_label} " +
                "--build-arg AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID " +
                "--build-arg AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY " +
                "--build-arg BUILDKIT_INLINE_CACHE=1 " +
                "--build-arg APT_REFRESH_KEY=${params.apt_refresh_key} .")
            }
            docker.withRegistry(params.docker_registry, docker_credentials) {
              parent_image.push()
            }
          }
        }
      }
      post {
        cleanup {
          library("tailor-meta@${params.tailor_meta}")
          cleanDocker()
          deleteDir()
        }
      }
    }

    stage("Setup recipes and pull sources") {
      agent any
      steps {
        script {
          def parent_image = docker.image(parentImage(params.release_label, params.docker_registry))
          retry(params.retries as Integer) {
            docker.withRegistry(params.docker_registry, docker_credentials) { parent_image.pull() }
          }

          parent_image.inside() {
            unstash(name: 'rosdistro')
            // Generate recipe configuration files
            def recipe_yaml = sh(
              script: "create_recipes --recipes $recipes_yaml --recipes-dir $recipes_dir " +
                      "--release-track $params.release_track --release-label $params.release_label --debian-version $params.timestamp",
              returnStdout: true).trim()

            // Script returns a mapping of recipe labels and paths
            recipes = readYaml(text: recipe_yaml)

            distributions = readYaml(file: recipes_yaml)['os'].collect {
              os, distribution -> distribution }.flatten()

            // Stash each recipe configuration individually for parallel build nodes
            recipes.each { recipe_label, recipe_path ->
              stash(name: recipeStash(recipe_label), includes: recipe_path)
            }

            // Pull down distribution sources
            withCredentials([string(credentialsId: 'tailor_github', variable: 'GITHUB_TOKEN')]) {
              sh "pull_distro_repositories --src-dir $src_dir --github-key $GITHUB_TOKEN " +
                "--recipes $recipes_yaml  --rosdistro-index $rosdistro_index --clean"
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
          library("tailor-meta@${params.tailor_meta}")
          cleanDocker()
          deleteDir()
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
                retry(params.retries as Integer) {
                  docker.withRegistry(params.docker_registry, docker_credentials) {
                    parent_image.pull()
                  }
                }
                parent_image.inside("-v $HOME/tailor/gpg:/gpg") {
                  unstash(name: 'rosdistro')

                  sh("mirror_upstream $upstream_yaml --version $params.timestamp --apt-repo $params.apt_repo " +
                     "--release-label $params.release_label --distribution $distribution --keys /gpg/*.key " +
                     "${params.force_mirror ? '--force-mirror' : ''} ${params.deploy ? '--publish' : ''}")
                }
              } finally {
                  library("tailor-meta@${params.tailor_meta}")
                  cleanDocker()
                  try {
                    deleteDir()
                  } catch (e) {
                    println e
                  }
              }
            }}]
          }
          parallel(jobs)
        }
      }
    }

    stage("Create packaging environment") {
      agent any
      steps {
        script {
          def jobs = distributions.collectEntries { distribution ->
            [distribution, { node {
              try {
                def parent_image = docker.image(parentImage(params.release_label, params.docker_registry))
                retry(params.retries as Integer) {
                  docker.withRegistry(params.docker_registry, docker_credentials) {parent_image.pull()}
                }

                def unionBuild = [] as Set
                def unionRun   = [] as Set
                parent_image.inside() {
                  unstash(name: srcStash(params.release_label))
                  recipes.each { recipe_label, recipe_path ->
                    unstash(recipeStash(recipe_label))
                    def recipe = readYaml(file: recipe_path)
                    def os_version = recipe['os_version']
                    if (os_version == distribution){
                      sh "ROS_PYTHON_VERSION=$params.python_version generate_bundle_templates --src-dir $src_dir --template-dir $debian_dir --recipe $recipe_path"
                      stash(name: debianStash(recipe_label), includes: "${debian_dir}/**", excludes: "${debian_dir}/rules-*,${debian_dir}/control-*,${debian_dir}/Dockerfile-*,${debian_dir}/tmp")
                      // Generate unique names for artifacts files
                      sh"""
                        find $debian_dir -type f \\( -name rules -o -name control \\) ! -name '*-$recipe_label' -exec mv {} {}-$recipe_label \\;
                        find $debian_dir -type f \\( -name Dockerfile \\) ! -name '*-$distribution' -exec mv {} {}-$distribution \\;
                      """
                      def updated_recipe = readYaml(file: recipe_path)
                      unionBuild.addAll(updated_recipe['build_depends'] ?: [])
                      unionRun.addAll(updated_recipe['run_depends'] ?: [])
                    }
                  }
                }
                def UNION_BUILD_DEPENDS = unionBuild.toList().sort().join(' ')
                def UNION_RUN_DEPENDS   = unionRun.toList().sort().join(' ')

                def bundle_image_label = bundleImage(params.release_label, distribution, params.docker_registry)
                def bundle_image = docker.image(bundle_image_label)
                try {
                  docker.withRegistry(params.docker_registry, docker_credentials) {bundle_image.pull()}
                } catch (all) {
                  echo("Unable to pull ${bundle_image_label} as a build cache")
                }

                retry(params.retries as Integer) {
                  withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'tailor_aws']]) {
                    bundle_image = docker.build(bundle_image_label,
                      "${params.invalidate_cache ? '--no-cache ' : ''} " +
                      "-f $debian_dir/Dockerfile-${distribution} --cache-from ${bundle_image_label} " +
                      "--build-arg AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID " +
                      "--build-arg AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY " +
                      "--build-arg UNION_BUILD_DEPENDS='${UNION_BUILD_DEPENDS}' " +
                      "--build-arg UNION_RUN_DEPENDS='${UNION_RUN_DEPENDS}' " +
                      "--build-arg BUILDKIT_INLINE_CACHE=1 " +
                      "--build-arg APT_REFRESH_KEY=${params.apt_refresh_key} $workspace_dir")
                  }
                }
                retry(params.retries as Integer) {
                  docker.withRegistry(params.docker_registry, docker_credentials) { bundle_image.push() }
                }
              } finally {
                  archiveArtifacts artifacts: "$debian_dir/rules*, $debian_dir/control*, $debian_dir/Dockerfile*", allowEmptyArchive: true

                  withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'tailor_aws']]) {
                    s3Upload(
                      bucket: params.apt_repo.replace('s3://', ''),
                      path: "${params.release_label}/dependencies",
                      includePathPattern: 'control*',
                      workingDir: "${debian_dir}",
                    )
                  }
                  library("tailor-meta@${params.tailor_meta}")
                  cleanDocker()
                  try {
                    deleteDir()
                  } catch (e) {
                    println e
                  }
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
                unstash(name: recipeStash(recipe_label))
                def os_version = readYaml(file: recipe_path)['os_version']
                def bundle_image = docker.image(bundleImage(params.release_label, os_version, params.docker_registry))
                retry(params.retries as Integer) {
                  docker.withRegistry(params.docker_registry, docker_credentials) { bundle_image.pull() }
                }
                bundle_image.inside("-v $HOME/tailor/ccache:/ccache -e CCACHE_DIR=/ccache") {
                // The cache sizes need to be consistent.
                // If the ccache gets larger than the Jenkins size below it will be discarded.
                // bundle_image.inside("-v $HOME/tailor/ccache:/ccache -e CCACHE_DIR=/ccache -e CCACHE_MAXSIZE=4900M") {
                  // // Invoke the Jenkins Job Cacher Plugin via the cache method.
                  // // Set the max cache size to 4GB, as S3 only allows a 5GB max upload at once
                  // cache(maxCacheSize: 4900, caches: [
                  //  arbitraryFileCache(path: '${HOME}/tailor/ccache', cacheName: recipe_label, compressionMethod: 'TARGZ_BEST_SPEED')
                  // ]) {
                  unstash(name: srcStash(params.release_label))
                  unstash(name: debianStash(recipe_label))
                  unstash(name: 'rosdistro')
                  common_config = readYaml(file: recipes_yaml)['common']
                  def colcon_cache_enabled = common_config.find{ it.key == "colcon_cache_enabled" }?.value

                  if (colcon_cache_enabled){
                    def restic_repo_url = common_config.find{ it.key == "restic_repository_url" }?.value
                    def distros = common_config.distributions.keySet()

                    def build_dir = pwd() + '/workspace/debian/tmp/build'
                    def cache_dir = 'workspace/debian/tmp/'
                    sh "mkdir -p $build_dir"
                    // Remove any .git directory that might exist in the ws.
                    // If a .git directory is present, colcon cache will use incorrectly a Githash to create the lock files
                    sh """
                      find . -name '.git' -print
                      find . -name '.git' -print -exec rm -rf {} +
                    """

                    withCredentials([
                    [$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'tailor_aws'],
                    string(credentialsId: 'tailor_restic_password', variable: 'RESTIC_PASSWORD'),
                    ]){
                      def restic_repo = "${restic_repo_url}/${params.release_label}/colcon-cache"
                      def exists = sh(
                        script: "restic -r ${restic_repo} cat config >/dev/null 2>&1",
                        returnStatus: true
                      )
                      if (exists != 0) {
                        sh "restic -r ${restic_repo} init"
                      }
                      sh("""
                        if restic -r ${restic_repo} snapshots --tag "${recipe_label}" --json 2>/dev/null | grep -q '"id"'; then
                          echo "Restoring colcon cache from restic (tag=${recipe_label})..."
                          restic -r ${restic_repo} restore latest --tag ${recipe_label} --target . || true
                        else
                          echo "No restic snapshot found for tag '${recipe_label}', skipping restore."
                        fi
                      """)

                      // Lock
                      distros.each { distro ->
                        sh """
                          cd ${src_dir}/${distro}
                          colcon cache lock --build-base ${build_dir}/${distro}
                        """
                      }
                      // Build
                      sh("""
                        ccache -z
                        cd $workspace_dir && debian/rules build
                        ccache -s -v
                      """)
                      // Store
                      sh("""
                        restic -r ${restic_repo} backup $cache_dir --tag ${recipe_label} --group-by tags --retry-lock 1m || true
                      """)
                      // Package
                      sh("""
                        ccache -z
                        cd $workspace_dir && fakeroot debian/rules binary
                        ccache -s -v
                      """)
                    }
                  }
                  else{
                    sh("""
                      ccache -z
                      cd $workspace_dir && dpkg-buildpackage -uc -us -b
                      ccache -s -v
                    """)
                  }

                  stash(name: packageStash(recipe_label), includes: "*.deb")
                }
              } finally {
                // Don't archive debs - too big. Consider s3 upload?
                // archiveArtifacts(artifacts: "*.deb", allowEmptyArchive: true)
                library("tailor-meta@${params.tailor_meta}")
                try {
                  if (fileExists(".")) {
                    deleteDir()
                  }
                } catch (e) {
                  println e
                }
                cleanDocker()
              }
            }}]
          }
          parallel(jobs)
        }
      }
      post {
        cleanup {
          script {
            node {
              unstash(name: 'rosdistro')
              common_config = readYaml(file: recipes_yaml)['common']
              def colcon_cache_enabled = common_config.find{ it.key == "colcon_cache_enabled" }?.value
              if (colcon_cache_enabled){
                def restic_repo_url = common_config.find{ it.key == "restic_repository_url" }?.value
                withCredentials([
                [$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'tailor_aws'],
                string(credentialsId: 'tailor_restic_password', variable: 'RESTIC_PASSWORD'),
                ]){
                  def restic_repo = "${restic_repo_url}/${params.release_label}/colcon-cache"
                  sh(""""
                    restic -r ${restic_repo} forget --retry-lock 1m --keep-last 2 --prune || true
                  """)
                }
              }
            }
          }
        }
      }
    }

    stage("Ship packages") {
      agent none
      steps {
        script {
          def jobs = distributions.collectEntries { distribution ->
            [distribution, { node {
              try {
                def parent_image = docker.image(parentImage(params.release_label, params.docker_registry))
                retry(params.retries as Integer) {
                  docker.withRegistry(params.docker_registry, docker_credentials) { parent_image.pull() }
                }

                parent_image.inside("-v $HOME/tailor/gpg:/gpg") {
                  recipes.each { recipe_label, recipe_path ->
                    if (recipe_label.contains(distribution)) {
                      unstash(name: packageStash(recipe_label))
                    }
                  }
                  unstash(name: 'rosdistro')
                  if (params.deploy) {
                    sh("publish_packages *.deb --release-label $params.release_label --apt-repo $params.apt_repo " +
                        "--keys /gpg/*.key --distribution $distribution " +
                        "${params.days_to_keep ? '--days-to-keep ' + params.days_to_keep : ''} " +
                        "${params.num_to_keep ? '--num-to-keep ' + params.num_to_keep : ''}")
                  }
                }
              } finally {
                library("tailor-meta@${params.tailor_meta}")
                cleanDocker()
                try {
                  deleteDir()
                } catch (e) {
                  println e
                }
              }
            }}]
          }
          parallel(jobs)
        }
      }
    }

    stage("Invalidate CDN's cache") {
      agent any
      steps {
        script {
          unstash(name: 'rosdistro')
          common_config = readYaml(file: recipes_yaml)['common']
          def distribution_id = common_config.find{ it.key == "cloudfront_distribution_id" }?.value

          if(distribution_id) {
            withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'tailor_aws']]) {
              cfInvalidate(distribution:distribution_id, paths:["/$params.release_label/ubuntu/dists/*"])
            }
          }
        }
      }
    }
  }
}
