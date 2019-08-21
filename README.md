# tailor-distro

## Installing packages

In order to have access to the packages published by tailor-distro, add it to your apt configuration:

- Download http://tailor.locusbots.io/userContent/auth.conf to `/etc/apt/auth.conf`.

Then execute:
```
sudo apt-get install -y apt-transport-https &&
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 142D5F1683E1528B &&

source /etc/os-release &&
echo "deb [arch=amd64] https://artifacts.locusbots.io/hotdog/ubuntu $VERSION_CODENAME main" | sudo tee /etc/apt/sources.list.d/locus-tailor.list &&
echo "deb [arch=amd64] https://artifacts.locusbots.io/hotdog/ubuntu $VERSION_CODENAME-mirror main" | sudo tee -a /etc/apt/sources.list.d/locus-tailor.list &&

sudo apt-get update && sudo apt-get install -y locusrobotics-dev-hotdog
```

## Get a working copy:

Both developing or managing tailor-distro currently requires a local working copy:

```
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install python3.6 python3.6-dev python3.6-venv

# TODO(pbovbel) allow pip install of tailor-distro and PR-based workflow for rosdistro management?
git clone git@github.com:locusrobotics/tailor-distro.git
python3.6 -m venv venv
source venv/bin/activate
python -m pip install -U pip
cd tailor-distro
python -m pip install -e .
```

## Management

This repository includes a variety of management commands:

### Query
Get a list of repositories from a distribution, using a set of filters.

```
# List of all repositories in ROS2 distribution
tailor_manage query --distro ros2

# Get a list of all unpinned repositories in ROS1 distribution coming from locusrobotics
tailor_manage query --distro ros1 --url-pattern '.*locusrobotics.*' --unpinned

# Get a list of all pinned repositories in ROS1 distribution _not_ from locusrobotics
tailor_manage query --distro ros1 --url-pattern '^((?!locusrobotics).)*$' --unpinned

# Get a list of all repositories in ROS2 distrubtion matching a name pattern
tailor_manage query --distro ros2 --name-pattern '.*rmw.*'
```

### Pin
Pin a repository in a distribution to the latest tag on the repository's development branch.

```
# Pin the ros_comm repository
tailor_manage pin --distro ros1 ros_comm

# Pin all unpinned repositories in ROS1 distribution from locusrobotics
tailor_manage pin --distro ros1 $(tailor_manage query --distro ros1 --url-pattern '.*locusrobotics.*' --unpinned)

# Pin all unpinned repositories in ROS1 distribution from outside locusrobotics
tailor_manage pin --distro ros1 $(tailor_manage query --distro ros1 --url-pattern '^((?!locusrobotics).)*$' --unpinned)
```

### Compare
Find differences in source repositories between a rosdistro and an upstream rosdistro.

```
# Check for differences in ros_comm repository between the ROS1 distribution and its upstream.
tailor_manage compare --distro ros1 ros_comm

# Get a detailed view of differences for all packages between the ROS1 distribution and its upstream.
tailor_manage compare --distro ros1 $(tailor_manage query --distro ros1) --missing

# Get a list of repositories that differ between the ROS1 distribution and an arbitrary ROS distribution
tailor_manage compare --distro ros1 \
--upstream-index http://gitlab.locusbots.io/locusrobotics/rosdistro/raw/master/index.yaml --upstream-distro hotdog \
--missing --raw
```

### Import
Import source repositories into a distribution from an upstream distribution.

```
# Add all missing packages to the ROS2 distribution from its default upstream
missing_packages=$(tailor_manage compare --distro ros2 --missing --raw)
tailor_manage import --distro ros2 $(missing_packages)

# Add all missing packages to the ROS1 distribution from an arbitrary upstream
missing_packages=$(tailor_manage compare --distro ros1 \
--upstream-index http://gitlab.locusbots.io/locusrobotics/rosdistro/raw/master/index.yaml --upstream-distro hotdog \
--missing --raw)
tailor_manage import --distro ros1 $missing_packages \
--upstream-index http://gitlab.locusbots.io/locusrobotics/rosdistro/raw/master/index.yaml --upstream-distro hotdog
```

### Release
Run typical bookkeeping to cut a release.

```
# Checkout a 'release' branch for the rosdistro repository
cd ~/rosdistro
git checkout -b release/19.1

# Gather all unpinned packages
packages=$(tailor_manage query --distro ros1 --unpinned)

# Run catkin_generate_changelog and catkin_prepare_release on all unpinned repos, while updating the rosdistro
tailor_manage release --distro ros1 --release 19.1 $packages
```

## Development

You can replicate the commands executed by CI locally, from the rosdistro repository

```
create_recipes --recipes config/recipes.yaml --recipes-dir ~/workspace/recipes --release-label hotdog --release-track hotdog --debian-version 0.0.0
pull_distro_repositories --src-dir ~/workspace/src --github-key $GITHUB_KEY --rosdistro-index rosdistro/index.yaml --recipes config/recipes.yaml --clean
generate_bundle_templates --src-dir ~/workspace/src --template-dir ~/workspace/templates --recipe ~/workspace/recipes/dev-bionic-hotdog.yaml
```


## Misc Notes:

### jenkins bringup

```
# Master
sudo yum update -y
sudo yum install -y docker
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -a -G docker ec2-user

sudo docker run -d \
  -u root \
  -p 80:8080 \
  -p 50000:50000 \
  -v /root/tailor/jenkins:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --env JAVA_OPTS="-Dhudson.slaves.WorkspaceList== -DBLUEOCEAN_FEATURE_AUTOFAVORITE_ENABLED=false" \
  --restart=always \
  --name jenkins-master \
  jenkinsci/blueocean

# Slave AMI
# 	Block device mapping: /dev/xvda=:64:true:gp2

#! /bin/bash
set -e

sudo yum update -y
sudo yum install -y docker git
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -a -G docker ec2-user
mkdir -p tailor/ccache
mkdir -p tailor/gpg

scp -i ~/.ssh/id_locus_aws.pem ../*.key ec2-user@ec2-34-227-29-127.compute-1.amazonaws.com:~/tailor/gpg
```

Script Approval:
```
method hudson.model.Job getBuilds
method hudson.model.Run getNumber
method hudson.model.Run isBuilding
method jenkins.model.Jenkins getItemByFullName java.lang.String
method org.jenkinsci.plugins.workflow.job.WorkflowRun doStop
staticMethod jenkins.model.Jenkins getInstance
staticMethod org.codehaus.groovy.runtime.DefaultGroovyMethods flatten java.util.List
staticMethod org.codehaus.groovy.runtime.DefaultGroovyMethods toInteger java.lang.Number
```

Extra plugins:
- Lockable Resources plugin
- Basic Branch Build Strategies Plugin
- Pipeline Utility Steps
- Amazon EC2
- Amazon ECR

Secrets:
- Add tailor_aws, tailor_github credentials
- Add gpg keys to /root/tailor/gpg
```
scp *.key tailor.locusbots.io:/root/tailor/gpg
```
