node {
  stage('Build') {
    // The first milestone step starts tracking concurrent build order
    milestone(1)
    echo "Building"
    echo "workspace is ${WORKSPACE}"
  }

  // This locked resource contains both Test stages as a single concurrency Unit.
  // Only 1 concurrent build is allowed to utilize the test resources at a time.
  // Newer builds are pulled off the queue first. When a build reaches the
  // milestone at the end of the lock, all jobs started prior to the current
  // build that are still waiting for the lock will be aborted
  echo "Locking"
  lock(resource: 'myResource', inversePrecedence: true){
    echo "Locked"
    parallel {
      'Unit Tests' : {
        echo "workspace is ${WORKSPACE}"
        echo "Unit Tests"
      },
      'System Tests' : {
        docker.image('ubuntu:bionic').inside {
          echo "workspace is ${WORKSPACE}"
          echo "System Tests"
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
    input "Deploy?"
    milestone(3)
    node {
      echo "Deploying"
    }
  }
}
