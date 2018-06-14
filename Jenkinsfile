#!/usr/bin/env groovy

// Learn groovy: https://learnxinyminutes.com/docs/groovy/

node {
  try{
    sh "env"

    def release_track = 'hotdog'
    def release_label = release_track
    def package_version = new Date().format('yyyyMMdd.HHmmss')

    def days_to_keep = 30
    def num_to_keep = 10
    def build_schedule = null

    // Create tagged release
    if (env.TAG_NAME != null) {
      release_track = env.TAG_NAME
      release_label = release_track + '-final'
      days_to_keep = null
    }
    // Create a release candidate
    else if (env.BRANCH_NAME.startsWith('release/')) {
      release_track = env.BRANCH_NAME - 'release/'
      release_label = release_track + '-rc'
    }
    // Create mystery meat package
    else if (env.BRANCH_NAME == 'master') {
      build_schedule = 'H/30 * * * *'
    }
    // Create a feature package
    else {
      release_label = release_track + '-' + env.BRANCH_NAME
    }

    // TODO(pbovbel) clean these up
    def projectProperties = [
      [$class: 'BuildDiscarderProperty', strategy: [$class: 'LogRotator', artifactDaysToKeepStr: days_to_keep.toString(), artifactNumToKeepStr: num_to_keep.toString(), daysToKeepStr: days_to_keep.toString(), numToKeepStr: num_to_keep.toString()]],
    ]
    if (build_schedule) {
      projectProperties.add(pipelineTriggers([cron(build_schedule)]))
    }
    properties(projectProperties)

    // Build parameters
    // TODO(pbovbel) look into using java libs for path concatenation
    def environment = [:]
    def parent_image = 'tailor/' + release_label + '-parent'
    def workspace_dir = 'catkin_ws/'
    def recipes = [:]
    def recipes_dir = workspace_dir + 'recipes/'
    def src_dir = workspace_dir + 'src/'
    def src_stash = release_label + '-src'
    def debian_dir = workspace_dir + 'debian/'

    // Build parameters as closures
    def bundleImage = { recipe_label -> 'tailor/' + recipe_label + "-bundle"}
    def debianStash = { recipe_label -> recipe_label + "-debian"}
    def packageStash = { recipe_label -> recipe_label + "-packages"}

    stage("Configure distribution") {
      node {
        milestone(1)
        try{
          dir('tailor-distro') {
            checkout(scm)
          }
          lock('docker_cache') {
            environment[parent_image] = docker.build(parent_image, "-f tailor-distro/environment/Dockerfile .")
          }
          environment[parent_image].inside {
            def recipe_yaml = sh(script: "create_recipes --recipes tailor-distro/rosdistro/recipes.yaml " +
              "--recipes-dir ${recipes_dir} --release-label ${release_label} --package-version ${package_version}", returnStdout: true).trim()
            recipes = readYaml(text: recipe_yaml)

            recipes.each { recipe_label, recipe_path ->
              stash(name: recipe_label, includes: recipe_path)
            }
          }
        }
        finally {
          archiveArtifacts(artifacts: recipes_dir + '**/*.yaml', fingerprint: true, allowEmptyArchive: true)
          cleanWs() }
      }
    }

    stage("Pull packages") {
      milestone(2)
      lock('distro-cache') {
        node {
          ws(dir: "$WORKSPACE/../distro_package_cache") {
            try {
              environment[parent_image].inside {
                withCredentials([string(credentialsId: 'tailor_github', variable: 'github_key')]) {
                  sh "pull_distro_repositories --src-dir ${src_dir} --github-key ${github_key} " +
                    "--repositories-file catkin.repos"
                  stash(name: src_stash, includes: src_dir)
                }
              }
            }
            finally {
              archiveArtifacts(artifacts: "catkin.repos", allowEmptyArchive: true)
              cleanWs()
            }
          }
        }
      }
    }

    stage('Build environment') {
      milestone(3)
      lock('docker-cache') {
        parallel(recipes.collectEntries { recipe_label, recipe_path ->
          [recipe_label, { node {
            try {
              environment[parent_image].inside {
                unstash(name: src_stash)
                unstash(name: recipe_label)
                sh "generate_bundle_templates --workspace-dir ${workspace_dir} --recipe ${recipe_path}"
                stash(name: debianStash(recipe_label), includes: debian_dir)
              }
              environment[bundleImage(recipe_label)] = docker.build(bundleImage(recipe_label), "-f ${workspace_dir}/Dockerfile .")
            }
            finally {
              archiveArtifacts(artifacts: debian_dir +'**', fingerprint: true, allowEmptyArchive: true)
              cleanWs()
            }
          }}]
        })
      }
    }

    stage("TODO Test bundle") {
      milestone(4)
      parallel(recipes.collectEntries { recipe_label, recipe_path ->
        [recipe_label, { node {
          try {
            environment[bundleImage(recipe_label)].inside('-v /tmp/ccache:/ccache') {
              unstash(name: src_stash)
              // sh 'cd workspace && catkin build && catkin run_tests && source install/setup.bash && catkin_test_results build'
              sh "ls -la ${workspace_dir}"
            }
          }
          finally { cleanWs() }
        }}]
      })
    }

    stage("Package bundle") {
      milestone(5)
      parallel(recipes.collectEntries { recipe_label, recipe_path ->
        [recipe_label, { node {
          try {
            environment[bundleImage(recipe_label)].inside('-v /var/lib/tailor/ccache:/ccache') {
              unstash(name: src_stash)
              unstash(name: debianStash(recipe_label))
              sh 'ccache -z'
              sh "cd ${workspace_dir} && dpkg-buildpackage -uc -us"
              sh 'ccache -s'  // show ccache stats after build
              stash(name: packageStash(recipe_label), includes: "*.deb")
            }
          }
          finally {
            archiveArtifacts(artifacts: "*.deb", fingerprint: true, allowEmptyArchive: true)
            cleanWs()
          }
        }}]
      })
    }

    stage("TODO Ship bundle") {
      milestone(6)
      lock('aptly') {
        parallel(recipes.collectEntries { recipe_label, recipe_path ->
          [recipe_label, { node {
            try {
              environment[parent_image].inside('-v /var/lib/tailor/aptly:/aptly') {
                unstash(name: packageStash(recipe_label))

                sh "ls -la *.deb"
                // TODO(pbovbel) upload package to apt repo
              }
            }
            finally { cleanWs() }
          }}]
        })
      }
    }
  }
  // catch(Exception exc) {
  //   TODO(pbovbel) error handling (email/slack/etc)
  // }

  finally {
    // TODO(pbovbel) find a way to clean cache periodically when no builds are active
    lock('docker-cache') {
      stage('Clean up docker') {
        sh 'docker image prune -f'
        sh 'docker image prune -af --filter="until=12h" --filter="label=origin=tailor.locusbots.io"'
      }
    }
  }

}
