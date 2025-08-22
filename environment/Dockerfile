FROM ubuntu:noble

LABEL tailor="environment"

SHELL ["/bin/bash", "-c"]

ARG AWS_ACCESS_KEY_ID
ENV AWS_ACCESS_KEY_ID ${AWS_ACCESS_KEY_ID}

ARG AWS_SECRET_ACCESS_KEY
ENV AWS_SECRET_ACCESS_KEY ${AWS_SECRET_ACCESS_KEY}

ENV DEBIAN_FRONTEND noninteractive
ENV PYTHONUNBUFFERED 1

ARG APT_REFRESH_KEY

RUN sed -i 's/archive.ubuntu.com/us-east-1.ec2.&/g' /etc/apt/sources.list
RUN echo "APT refresh key=${APT_REFRESH_KEY}"
RUN apt-get update && apt-get install --no-install-recommends -y locales curl gnupg1 sudo
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8

RUN apt-get update && apt-get install --no-install-recommends -y \
  bzip2 \
  python3-dev \
  python3-pip \
  python3-setuptools \
  python3-wheel \
  git \
  ruby \
  ruby-bundler \
  vim \
  xz-utils

# Install aptly for managing mirror debs
RUN curl -LO --output-dir /tmp https://github.com/aptly-dev/aptly/releases/download/v1.5.0/aptly_1.5.0_linux_amd64.tar.gz && \
    tar xzf /tmp/aptly_1.5.0_linux_amd64.tar.gz --strip-components 1 -C /usr/local/bin

# Install locusrobotics deb-s3 fork for managing bundle debs
RUN git clone -b master-noble https://github.com/locusrobotics/deb-s3.git && \
    cd deb-s3 && bundle update --bundler && bundle install && ln -sf $(pwd)/bin/deb-s3 /usr/local/bin/deb-s3

# Build and install rosdistro
COPY tailor-distro tailor-distro
RUN pip3 install -e tailor-distro --break-system-packages

# Inject the rosdep definitions from source
RUN if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]] ; then rosdep init ; fi
RUN echo "yaml file:///etc/ros/rosdep/rosdep.yaml" > /etc/ros/rosdep/sources.list.d/10-tailor.list
COPY rosdistro/rosdep/rosdep.yaml /etc/ros/rosdep/rosdep.yaml

RUN usermod -md /home/tailor -s /bin/bash -l tailor ubuntu && \
    groupmod -n tailor ubuntu && \
    echo "tailor:tailor" | chpasswd && \
    echo "tailor ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers
USER tailor

RUN rosdep update
