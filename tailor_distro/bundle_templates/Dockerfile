FROM {{ os_name }}:{{ os_version }}

LABEL origin="tailor.locusbots.io"

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && apt-get install --no-install-recommends -y locales curl gnupg
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8

RUN apt-get update && apt-get install --no-install-recommends -y ccache && \
    ccache -M 5G && \
    ccache --set-config=cache_dir=/ccache

# TODO(pbovbel) create a locus repository mirror
RUN echo "deb http://repositories.ros.org/ubuntu/testing/ {{ os_version }} main" > /etc/apt/sources.list.d/ros-latest.list && \
    curl --silent http://repositories.ros.org/repos.key | apt-key add -

# install build and run dependencies
# TODO(pbovbel) remove regex_replace, but apt doesn't allow installing constrained dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
  {{ build_depends | union(run_depends) | sort | join(' ') | regex_replace('\(.*?\)', '') }}
