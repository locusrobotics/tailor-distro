#!/usr/bin/env groovy

// Learn groovy: https://learnxinyminutes.com/docs/groovy/

node {
  try{
    sh "env"

    def series = null
    def version = new Date().format('yyyyMMdd.HHmmss')

    def days_to_keep = null
    def num_to_keep = null
    def build_schedule = null

    // Create tagged release
    if (env.TAG_NAME != null) {
      series = env.TAG_NAME
      num_to_keep = 10
    }
    // Create a release sausage
    else if (env.BRANCH_NAME == 'master') {
      series = 'hotdog'
      days_to_keep = 10
      num_to_keep = 10
      build_schedule = 'H/30 * * * *'
    }
    // TODO(pbovbel release candidates
    // else if (env.BRANCH_NAME.startsWith('rc/')) {
    //   series = 'release'
    //   version = env.BRANCH_NAME
    // }
    // Create a 'feature' release
    else {
      series = env.BRANCH_NAME
      days_to_keep = 30
      num_to_keep = 10
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
    def parent_image = 'tailor/' + series + '-parent'
    def workspace_dir = 'catkin_ws/'
    def recipes = [:]
    def recipes_dir = workspace_dir + 'recipes/'
    def src_dir = workspace_dir + 'src/'
    def src_stash = series + '-src'
    def debian_dir = workspace_dir + 'debian/'

    // Build parameters as closures
    def bundleImage = { recipe_name -> 'tailor/' + recipe_name + "-bundle"}
    def debianStash = { recipe_name -> recipe_name + "-debian"}
    def packageStash = { recipe_name -> recipe_name + "-packages"}

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
              "--recipes-dir ${recipes_dir} --series ${series} --version ${version}", returnStdout: true).trim()
            recipes = readYaml(text: recipe_yaml)

            recipes.each { recipe_name, recipe_path ->
              stash(name: recipe_name, includes: recipe_path)
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
        parallel(recipes.collectEntries { recipe_name, recipe_path ->
          [recipe_name, { node {
            try {
              environment[parent_image].inside {
                unstash(name: src_stash)
                unstash(name: recipe_name)
                sh "generate_bundle_templates --workspace-dir ${workspace_dir} --recipe ${recipe_path}"
                stash(name: debianStash(recipe_name), includes: debian_dir)
              }
              environment[bundleImage(recipe_name)] = docker.build(bundleImage(recipe_name), "-f ${workspace_dir}/Dockerfile .")
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
      parallel(recipes.collectEntries { recipe_name, recipe_path ->
        [recipe_name, { node {
          try {
            environment[bundleImage(recipe_name)].inside('-v /tmp/ccache:/ccache') {
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
      parallel(recipes.collectEntries { recipe_name, recipe_path ->
        [recipe_name, { node {
          try {
            environment[bundleImage(recipe_name)].inside('-v /var/lib/tailor/ccache:/ccache') {
              unstash(name: src_stash)
              unstash(name: debianStash(recipe_name))
              sh 'ccache -z'
              sh "cd ${workspace_dir} && dpkg-buildpackage -uc -us"
              sh 'ccache -s'  // show ccache stats after build
              stash(name: packageStash(recipe_name), includes: "*.deb")
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
      lock('aptly')
      parallel(recipes.collectEntries { recipe_name, recipe_path ->
        [recipe_name, { node {
          try {
            environment[parent_image].inside('-v /var/lib/tailor/aptly:/aptly') {
              unstash(name: packageStash(recipe_name))
              sh "ls -la *.deb"
              // TODO(pbovbel) upload package to apt repo
            }
          }
          finally { cleanWs() }
        }}]
      })
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
