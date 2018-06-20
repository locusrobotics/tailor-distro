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

Secrets:
- Add tailor_aws, tailor_github credentials
- Configure keyrings in /var/lib/tailor/gnupg using gpg1, until aptly supports gpg2 (https://github.com/aptly-dev/aptly/issues/657)
```
sudo GNUPGHOME=/var/lib/tailor/gnupg gpg1 --import *.key
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
pip3 install -e tailor-distro
ROSDISTRO_INDEX_URL=file://$(pwd)/tailor-distro/rosdistro/index.yaml

create_recipes --recipes tailor-distro/rosdistro/recipes.yaml --recipes-dir recipes --release-label hotdog --debian-version 0.0.0
pull_distro_repositories --src-dir workspace/src --github-key asdfasdf --recipes tailor-distro/rosdistro/recipes.yaml
generate_bundle_templates --src-dir workspace/src --template-dir workspace --recipe recipes/dev-xenial-hotdog.yaml


```
