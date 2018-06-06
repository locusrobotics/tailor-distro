node {
  stage('Checkout and initialize') {
    checkout scm
    // The first milestone step starts tracking concurrent build order
    milestone(1)
    echo "Building"
    sh 'env'
    sh 'mkdir asdf'
    sh 'touch asdf/stage1a'
    sh 'touch asdf/stage1b'
    stash name: "mystash", includes: 'asdf/*'
    sh 'ls -la asdf'
    cleanWs()
  }

  // This locked resource contains both Test stages as a single concurrency Unit.
  // Only 1 concurrent build is allowed to utilize the test resources at a time.
  // Newer builds are pulled off the queue first. When a build reaches the
  // milestone at the end of the lock, all jobs started prior to the current
  // build that are still waiting for the lock will be aborted
  lock(resource: 'myResource', inversePrecedence: true){
    stage ('Parallel stage') {
      parallel {
        'Unit Tests' : {
          stage('Unit Tests') {
            node {
              ws {
                echo "Unit Tests"
                sh 'env'
                unstash name: "mystash"
                sh 'touch asdf/stage1c'
                sh 'ls -la asdf'
                cleanWs()
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
      }
    }
    milestone(2)
  }

  // The Deploy stage does not limit concurrency but requires manual input
  // from a user. Several builds might reach this step waiting for input.
  // When a user promotes a specific build all preceding builds are aborted,
  // ensuring that the latest code is always deployed.
  stage('Deploy') {
    // input "Deploy?"
    milestone(3)
    node {
      echo "Deploying"
      sh 'env'
      cleanWs()
    }
  }
}
