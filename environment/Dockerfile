FROM ubuntu:bionic

LABEL tailor="parent"

SHELL ["/bin/bash", "-c"]

ARG AWS_ACCESS_KEY_ID
ENV AWS_ACCESS_KEY_ID ${AWS_ACCESS_KEY_ID}

ARG AWS_SECRET_ACCESS_KEY
ENV AWS_SECRET_ACCESS_KEY ${AWS_SECRET_ACCESS_KEY}

ENV DEBIAN_FRONTEND noninteractive
ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install --no-install-recommends -y locales curl gnupg1
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

# TODO(pbovbel) Get this fix https://github.com/ros-infrastructure/catkin_pkg/pull/221
RUN pip3 install -U --force-reinstall --no-deps \
  git+https://github.com/ros-infrastructure/catkin_pkg.git@1c6ca153b43d6c8edec23f0f0059258e26a28086

# TODO(pbovbel) Get shallow clone pull
RUN pip3 install -U --force-reinstall --no-deps    \
  git+https://github.com/paulbovbel/vcstool.git@shallow-clone

RUN echo "deb http://repo.aptly.info/ squeeze main" > /etc/apt/sources.list.d/aptly.list && \
    curl --silent https://www.aptly.info/pubkey.txt | apt-key add - && \
    apt-get update && apt-get install --no-install-recommends -y aptly

COPY tailor-distro/environment/aptly.conf /root/.aptly.conf

COPY tailor-distro/rosdistro /etc/ros/rosdistro
ENV ROSDISTRO_INDEX_URL file:///etc/ros/rosdistro/index.yaml

COPY tailor-distro/rosdep /etc/ros/rosdep
RUN rosdep update

COPY tailor-distro tailor-distro
RUN pip3 install -e tailor-distro
