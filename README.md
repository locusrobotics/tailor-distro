# tailor-distro

## Installing packages

In order to have access to the packages published by tailor-distro, add it to your apt configuration:

```
# TODO(pbovbel) create a locus repository mirror,
# Pull python-catkin*
echo "deb [arch=amd64] http://repositories.ros.org/ubuntu/testing/ {{ os_version }} main" | sudo tee /etc/apt/sources.list.d/ros-latest.list &&
curl --silent http://repositories.ros.org/repos.key | sudo apt-key add -

# Pull libopensplice*
echo "deb [arch=amd64] http://repo.ros2.org/ubuntu/main {{ os_version }} main" | sudo tee /etc/apt/sources.list.d/ros2-latest.list && \
curl --silent http://repo.ros2.org/repos.key | sudo apt-key add -

# Pull gazebo*, libgazebo*
echo "deb [arch=amd64] http://packages.osrfoundation.org/gazebo/ubuntu-stable {{ os_version }} main" | sudo tee /etc/apt/sources.list.d/gazebo-latest.list && \
curl --silent http://packages.osrfoundation.org/gazebo.key | sudo apt-key add -

# Pull opencv3 for xenial
sudo add-apt-repository -y ppa:timsc/opencv-3.2

# Pull apt-boto-s3
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 379CE192D401AB61
echo "deb http://dl.bintray.com/lucidsoftware/apt/ lucid main" | sudo tee /etc/apt/sources.list.d/lucidsoftware-bintray.list
sudo apt-get update
sudo apt-get install apt-boto-s3

# Pull packages proper
echo "deb [arch=amd64] s3://AKIAIHKFLRIWBW63YWAQ:{{ aws_secret_access_key }}@s3.amazonaws.com/tailor-packages/ hotdog main" | sudo tee /etc/apt/sources.list.d/locus.list
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv 142D5F1683E1528B
sudo apt-get update
```

## Get a working copy:

Both developing or managing tailor-distro currently requires a local working copy:

```
git clone git@github.com:locusrobotics/tailor-distro.git
python3.6 -m venv venv
source venv/bin/activate
python -m pip install -U pip
cd tailor-distro
python -m pip install -e .
```

# TODO(pbovbel) allow pip install of tailor-distro and PR-based workflow for rosdistro management?

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

## Development

You can replicate the commands executed by CI locally:

```
ROSDISTRO_INDEX_URL=file://$(pwd)/tailor-distro/rosdistro/index.yaml
create_recipes --recipes tailor-distro/rosdistro/recipes.yaml --recipes-dir recipes --release-label hotdog --debian-version 0.0.0
pull_distro_repositories --src-dir workspace/src --github-key asdfasdf --recipes tailor-distro/rosdistro/recipes.yaml
generate_bundle_templates --src-dir workspace/src --template-dir workspace --recipe recipes/dev-xenial-hotdog.yaml
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
  --env JAVA_OPTS=-Dhudson.slaves.WorkspaceList== \
  --restart=always \
  --name jenkins-master \
  jenkinsci/blueocean

# Slave
# 	Block device mapping: /dev/xvda=:64:true:gp2

#! /bin/bash
set -e

sudo yum update -y
sudo yum install -y docker git
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -a -G docker ec2-user
mkdir -p tailor/ccache

```

Script Approval:
```
method hudson.model.Job getBuilds
method hudson.model.Run getNumber
method hudson.model.Run isBuilding
method jenkins.model.Jenkins getItemByFullName java.lang.String
staticMethod jenkins.model.Jenkins getInstance
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

### Names of things

Apt Distribution / Release Track:

- hotdog
- 18-2
- 18-1 (includes -rc and -final)

Apt Components (internal vs. upstream mirror):

- main
- mirror

Install location:

- `/opt/locus/{{ track }}/{{ flavour }}/setup.bash`

Flavour:

- dev
- bot
- wrangler

Package name:

- locus-wrangler-hotdog_{{ version }}
- locus-wrangler-upload-packages_{{ version }}
- locus-wrangler-18-1-rc_{{ version }}
- locus-wrangler-18-1-final_{{ version }}
- locus-{{ flavour }}-{{ release_label }}_{{ version }}

ROS_DISTRO:

- `{{ track }}-{{ flavour }}`
