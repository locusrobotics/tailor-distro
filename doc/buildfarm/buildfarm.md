## Job Structure

- 'distro' repo can serve as a global source of truth on what is packaged where.
  - distro-repo tags can be used to manage releases
  - Branches can be used to manage 'experiments', such as a different compiler or version of python
- 1 set of distro jobs responsible for:
  - catkin/ament release builds (devel and tagged builds)
  - packaging
  - imaging
  - deploying artifacts
  - doc builds
- N sets of package jobs reponsible for:
  - test/commit builds
  - PR integration

## Travis/CircleCI as the buildfarm

- Fairly limited in terms of environment
- Still can't find anything that supports the concept of upstream/dependent jobs
- Expensive when we want to scale

## Jenkins as the buildfarm

- Modern jenkins supports the 'pipelines' DSL
  - These are defined either inside repositories (travis/circleci style), or in a freestyle job
  - Jenkins pipelines *can* have upstream dependencies, which is a bit step up over hosted CI like travis
- The distro-pipeline can dynamically generate a pipeline for each catkin/ament package.
  - PR builds are natively supported in jenkins pipelines
  - It can trigger the downstream distro-pipeline, or we can run the distro-pipeline on a cron schedule.

## Run and deploy

Jenkins is super easy to run:

```
docker run \
  -u root \
  --rm \
  -p 8080:8080 \
  -p 50000:50000 \
  -v ~/locus_build/jenkins_data:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  jenkinsci/blueocean
```

The docker can run on any variety of AWS infra:
  - EC2
  - Lightsail
  - ECS cluster

- We should consider making sure we can autoscale jenkins right off the bat, since we're going to churn through a lot of builds. This informs how we deploy our jenkins setup.
  - Probably the easiest way to autoscale is to spin up a new VM 'jenkins slave'
    - there's some jenkins plugins to that effect
    - Provisioning the jenkins slave automatically seems tricky.
    - We may be able to have a jenkins job create an AMI specifically to use for slaves.

- Ansible is my go-to, and it has a fairly complete amount of AWS plugins to handle provisioning. However, certain tools like terraform may make it easier to make an auto-scaling EC2 setup.
