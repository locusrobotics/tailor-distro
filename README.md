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
