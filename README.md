# locus_build

Temporary notes and experiments in build and packaging infrastructure

docker build -f build/Dockerfile .

# jenkins bringup

```
curl -fsSL get.docker.com | sh

sudo docker run -d \
  -u root \
  -p 80:8080 \
  -p 50000:50000 \
  -v ~/jenkins_data:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --env JAVA_OPTS=-Dhudson.slaves.WorkspaceList== \
  --restart=always \
  --name jenkins \
  jenkinsci/blueocean
```

Extra plugins:
- Lockable Resources plugin
- Basic Branch Build Strategies Plugin
- Pipeline Utility Steps

Add tailor_aws and tailor_github credentials


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
mkdir venv
virtualenv venv --python /usr/bin/python3
source venv/bin/activate
pip3 install -e tailor-distro
ROSDISTRO_INDEX_URL=file://$(pwd)/tailor-distro/rosdistro/index.yaml

create_recipes --recipes tailor-distro/rosdistro/recipes.yaml --recipes-dir recipes --release-label hotdog --debian-version 0.0.0
pull_distro_repositories --src-dir workspace/src --github-key asdfasdf --repositories-file ros1.repos --recipes tailor-distro/rosdistro/recipes.yaml
generate_bundle_templates --src-dir workspace/src --template-dir workspace --recipe recipes/dev-xenial-hotdog.yaml


```
