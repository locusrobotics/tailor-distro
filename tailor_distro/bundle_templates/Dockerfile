FROM {{ distro }}:{{ codename }}

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && apt-get install --no-install-recommends -y locales curl
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8

# TODO(pbovbel) create a locus repository mirror
RUN source /etc/os-release && \
    echo "deb http://repositories.ros.org/ubuntu/testing/ $VERSION_CODENAME main" > /etc/apt/sources.list.d/ros-latest.list
RUN curl --silent http://repositories.ros.org/repos.key | apt-key add -

# install build and run dependencies
# TODO(pbovbel) remove regex_replace, but apt doesn't allow installing constrained dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
  {{ build_depends | union(run_depends) | sort | join(' ') | regex_replace('\(.*?\)', '') }}
