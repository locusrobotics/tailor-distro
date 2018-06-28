# tailor-distro

sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 379CE192D401AB61
echo "deb http://dl.bintray.com/lucidsoftware/apt/ lucid main" | sudo tee /etc/apt/sources.list.d/lucidsoftware-bintray.list
sudo apt-get update
sudo apt-get install apt-boto-s3

echo "deb [arch=amd64] s3://AKIAIHKFLRIWBW63YWAQ:{{ aws_secret_access_key }}@s3.amazonaws.com/tailor-packages/ hotdog main" | sudo tee /etc/apt/sources.list.d/locus.list
sudo apt-key adv --keyserver keyserver.ubuntu.com --recv 142D5F1683E1528B
sudo apt-get update

# jenkins bringup

```
# Master
sudo yum update -y
sudo yum install -y docker
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -a -G docker ec2-user

sudo docker run -d \
  -u $USER:$USER \
  -p 80:8080 \
  -p 50000:50000 \
  -v /home/$USER/tailor/jenkins:/var/jenkins_home \
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

# Slave init NG?
#! /bin/bash
set -e

sudo yum update -y
sudo yum install -y docker git
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -a -G docker ec2-user

cat << EOF > Dockerfile
FROM jenkinsci/jnlp-slave

USER root

RUN apt-get update && apt-get -y install \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg2 \
    software-properties-common \
    git

RUN curl -fsSL https://download.docker.com/linux/debian/gpg | apt-key add - && \
    add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/debian stretch stable" && \
    cat /etc/apt/sources.list

RUN apt-get update && apt-get -y install docker-ce
EOF

sudo docker build -t jenkins-slave .

JENKINS_URL=http://tailor.locusbots.io
AWS_INSTANCE_ID=$(curl http://169.254.169.254/latest/meta-data/instance-id)
JENKINS_AMI_DESCRIPTION=Linux
SLAVE_URI="${JENKINS_AMI_DESCRIPTION}%20($AWS_INSTANCE_ID)"
API_TOKEN=7f7d2b48489a40d0fb05eebb721583fa

sudo docker run --rm -it \
  -u root \
  -v /var/lib/tailor/jenkins:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --env JAVA_OPTS=-Dhudson.slaves.WorkspaceList== \
  --name jenkins-slave \
  jenkins-slave \
  -workDir=/var/jenkins_home \
  -jnlpUrl "${JENKINS_URL}/computer/${SLAVE_URI}/slave-agent.jnlp" \
  -jnlpCredentials $API_TOKEN
```

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
- Add gpg keys to /var/lib/tailor/gpg
```
scp *.key tailor.locusbots.io:/var/lib/tailor/gpg
```

# Names of things

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

# DYI

Run tailor-distro yourself:

```
git clone git@github.com:locusrobotics/tailor-distro.git
python3.6 -m venv venv
source venv/bin/activate
python -m pip install -U pip
python -m pip install -e tailor-distro
ROSDISTRO_INDEX_URL=file://$(pwd)/tailor-distro/rosdistro/index.yaml

create_recipes --recipes tailor-distro/rosdistro/recipes.yaml --recipes-dir recipes --release-label hotdog --debian-version 0.0.0
pull_distro_repositories --src-dir workspace/src --github-key asdfasdf --recipes tailor-distro/rosdistro/recipes.yaml
generate_bundle_templates --src-dir workspace/src --template-dir workspace --recipe recipes/dev-xenial-hotdog.yaml


```
