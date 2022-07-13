FROM ubuntu:bionic

LABEL tailor="environment"

SHELL ["/bin/bash", "-c"]

ARG AWS_ACCESS_KEY_ID
ENV AWS_ACCESS_KEY_ID ${AWS_ACCESS_KEY_ID}

ARG AWS_SECRET_ACCESS_KEY
ENV AWS_SECRET_ACCESS_KEY ${AWS_SECRET_ACCESS_KEY}

ENV DEBIAN_FRONTEND noninteractive
ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install --no-install-recommends -y locales curl gnupg1 sudo
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8

RUN apt-get update && apt-get install --no-install-recommends -y \
  python-rosdep \
  python3-dev \
  python3-pip \
  python3-setuptools \
  python3-wheel \
  git \
  ruby \
  ruby-bundler \
  xz-utils

# Install aptly for managing mirror debs
RUN echo "deb http://repo.aptly.info/ squeeze main" >> /etc/apt/sources.list && \
    curl --silent https://www.aptly.info/pubkey.txt | apt-key add - && \
    apt-get update && apt-get install --no-install-recommends -y aptly

# Install locusrobotics deb-s3 fork for managing bundle debs
RUN git clone https://github.com/locusrobotics/deb-s3.git && \
    cd deb-s3 && bundle install && ln -sf $(pwd)/bin/deb-s3 /usr/local/bin/deb-s3

# Inject the rosdep definitions from source
RUN rosdep init
RUN echo "yaml file:///etc/ros/rosdep/rosdep.yaml" > /etc/ros/rosdep/sources.list.d/10-tailor.list
COPY rosdistro/rosdep/rosdep.yaml /etc/ros/rosdep/rosdep.yaml

COPY tailor-distro tailor-distro
RUN pip3 install -e tailor-distro

RUN groupadd -r tailor && useradd -ms /bin/bash -g tailor -G sudo tailor
USER tailor

RUN mkdir -p /home/tailor && \
    usermod -d /home/tailor tailor

RUN rosdep update
