FROM ubuntu:bionic

LABEL origin="tailor.locusbots.io"

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && apt-get install --no-install-recommends -y locales curl gnupg
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8

RUN apt-get update && apt-get install --no-install-recommends -y \
  python3-dev \
  python3-pip \
  python3-setuptools \
  python3-wheel \
  git

RUN pip3 install \
  bloom \
  catkin_pkg \
  Jinja2 \
  PyYaml \
  rosdistro \
  vcstool

RUN echo "deb http://repo.aptly.info/ squeeze main" > /etc/apt/sources.list.d/aptly.list && \
    curl --silent https://www.aptly.info/pubkey.txt | apt-key add - && \
    apt-get update && apt-get install --no-install-recommends -y aptly

COPY tailor-distro tailor-distro

RUN pip3 install -e tailor-distro

COPY tailor-distro/rosdep /etc/ros/rosdep

ENV ROSDISTRO_INDEX_URL file:///tailor-distro/rosdistro/index.yaml

RUN rosdep update
