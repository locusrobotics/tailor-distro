#!/usr/bin/env groovy

// Learn groovy: https://learnxinyminutes.com/docs/groovy/

node {
  def docker_cache_lock = 'docker-cache'
  def aptly_lock = 'aptly'

  try{
    sh 'env'  // Dump environment for debugging purposes

    cancelPreviousBuilds()

    def release_track = 'hotdog'
    def release_label = release_track
    def debian_version = new Date().format('yyyyMMdd.HHmmss')

    def days_to_keep = 30
    def num_to_keep = 30
    def build_schedule = null

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

    // Build parameters
    // TODO(pbovbel) look into using java libs for path concatenation
    def docker_registry = '084758475884.dkr.ecr.us-east-1.amazonaws.com/tailor'
    def docker_registry_uri = 'https://' + docker_registry
    def docker_credentials = 'ecr:us-east-1:tailor_aws'
    def environment = [:]
    def parent_image = docker_registry + ':' + release_label + '-parent'
    def workspace_dir = 'workspace'
    def recipes = [:]
    def recipes_config_stash = "recipes_config"
    def recipes_config_path = 'tailor-distro/rosdistro/recipes.yaml'
    def recipes_dir = workspace_dir + '/recipes'
    def src_dir = workspace_dir + '/src'
    def src_stash = release_label + '-src'
    def debian_dir = workspace_dir + '/debian'

    // Build parameters as closures
    def bundleImage = { recipe_label -> docker_registry + ':' + recipe_label + "-bundle"}
    def debianStash = { recipe_label -> recipe_label + "-debian"}
    def packageStash = { recipe_label -> recipe_label + "-packages"}
    def recipeStash = { recipe_label -> recipe_label + "-recipes"}

    stage("Configure distribution") {
      node {
        try {
          dir('tailor-distro') {
            checkout(scm)
          }
          withCredentials([[$class: 'AmazonWebServicesCredentialsBinding', credentialsId: 'tailor_aws']]) {
            environment[parent_image] = docker.build(parent_image, "-f tailor-distro/environment/Dockerfile " +
              "--build-arg AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID " +
              "--build-arg AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY .")
          }
          docker.withRegistry(docker_registry_uri, docker_credentials) {
            environment[parent_image].push()
          }

          environment[parent_image].inside() {
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
              stash(name: src_stash, includes: "$src_dir/")
            }
          }
        }
        finally {
          junit(testResults: 'tailor-distro/test-results.xml', allowEmptyResults: true)
          archiveArtifacts(artifacts: "$recipes_dir/*.yaml", allowEmptyArchive: true)
          archiveArtifacts(artifacts: "**/*.repos", allowEmptyArchive: true)
          deleteDir()
          // If two docker prunes run simulataneously, one will fail, hence || true
          sh 'docker image prune -af --filter="until=1h" --filter="label=tailor" || true'
        }
      }
    }

    stage('Create environment') {
      parallel(recipes.collectEntries { recipe_label, recipe_path ->
        [recipe_label, {
          node {
            try {
              docker.withRegistry(docker_registry_uri, docker_credentials) {
                environment[parent_image].pull()
              }
              environment[parent_image].inside() {
                unstash(name: src_stash)
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
      })
    }

    // stage("Test packages (TODO)") {
    //   parallel(recipes.collectEntries { recipe_label, recipe_path ->
    //     [recipe_label, { node {
    //       try {
    //         environment[bundleImage(recipe_label)].inside('-v $HOME/tailor/ccache:/ccache') {
    //           unstash(name: src_stash)
    //           // TODO(pbovbel):
    //           // Figure out how to run tests only on internal packages. We probably just want to run the tests
    //           // on the dev bundle, since it's a waste to redo them for 'lesser' bundles. Maybe pull_distro can
    //           // generate a list of packages coming from the locusrobotics organization?
    //           // sh 'cd workspace && catkin build && catkin run_tests &&
    //           // source install/setup.bash && catkin_test_results build'
    //           sh "ls -la $src_dir/ros1"
    //           sh "ls -la $src_dir/ros2"
    //         }
    //       }
    //       finally { deleteDir() }
    //     }}]
    //   })
    // }

    stage("Bundle packages") {
      parallel(recipes.collectEntries { recipe_label, recipe_path ->
        [recipe_label, { node {
          try {
            docker.withRegistry(docker_registry_uri, docker_credentials) {
              environment[bundleImage(recipe_label)].pull()
            }
            environment[bundleImage(recipe_label)].inside("-v $HOME/tailor/ccache:/ccache") {
              unstash(name: src_stash)
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
      })
    }

    stage("Ship packages") {
      node('master') {
        try {
          docker.withRegistry(docker_registry_uri, docker_credentials) {
            environment[parent_image].pull()
          }
          environment[parent_image].inside("-v $HOME/tailor/aptly:/aptly -v $HOME/tailor/gpg:/gpg") {
            recipes.each { recipe_label, recipe_path ->
              unstash(name: packageStash(recipe_label))
            }
            lock(aptly_lock) {
              sh("publish_packages *.deb --release-track $release_track --endpoint s3:tailor-packages: " +
                "--keys /gpg/*.key --days-to-keep $days_to_keep --num-to-keep $num_to_keep")
            }
          }
        }
        finally {
          deleteDir()
          sh 'docker image prune -af --filter="until=1h" --filter="label=tailor" || true'
        }
      }
    }
  }
  catch(Exception exc) {
    // TODO(pbovbel) error handling (email/slack/etc)
    throw exc
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
