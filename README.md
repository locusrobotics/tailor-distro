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
