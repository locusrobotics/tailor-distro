FROM ubuntu:bionic

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && apt-get install --no-install-recommends -y locales
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

COPY tailor-distro tailor-distro

RUN pip3 install -e tailor-distro
