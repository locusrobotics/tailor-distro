FROM ubuntu:focal AS base

LABEL tailor="environment"

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install --no-install-recommends -y \
    locales \
    curl \
    gnupg1 \
    sudo \
    python3-rosdep \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    git \
    ruby \
    ruby-bundler \
    xz-utils && \
    locale-gen en_US.UTF-8 && \
    rm -rf /var/lib/apt/lists/*

# Install aptly for managing mirror debs
RUN echo "deb http://repo.aptly.info/ squeeze main" >> /etc/apt/sources.list && \
    curl --silent https://www.aptly.info/pubkey.txt | apt-key add - && \
    apt-get update && \
    apt-get install --no-install-recommends -y aptly && \
    rm -rf /var/lib/apt/lists/*

FROM base AS debs3-build

WORKDIR /opt
# Install locusrobotics deb-s3 fork for managing bundle debs
RUN git clone https://github.com/locusrobotics/deb-s3.git && \
    cd deb-s3 && \
    bundle update --bundler && \
    bundle install

FROM base AS rosdep-tailor

# Inject the rosdep definitions from source
COPY rosdistro/rosdep/rosdep.yaml /etc/ros/rosdep/rosdep.yaml
RUN if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]] ; then rosdep init ; fi && \
     echo "yaml file:///etc/ros/rosdep/rosdep.yaml" > /etc/ros/rosdep/sources.list.d/10-tailor.list && \
     rosdep update

COPY tailor-distro tailor-distro
RUN pip3 install -e tailor-distro

FROM rosdep-tailor AS dev

ARG AWS_ACCESS_KEY_ID
ARG AWS_SECRET_ACCESS_KEY
ENV AWS_ACCESS_KEY_ID ${AWS_ACCESS_KEY_ID} \
    AWS_SECRET_ACCESS_KEY ${AWS_SECRET_ACCESS_KEY}
ARG USER_NAME=tailor

# Copy the deb-s3 binary
COPY --from=debs3-build /opt/deb-s3 /opt/deb-s3
COPY --from=debs3-build /var/lib/gems /var/lib/gems
RUN ln -sf /opt/deb-s3/bin/deb-s3 /usr/local/bin/deb-s3

RUN groupadd -r  "$USER_NAME" && useradd -ms /bin/bash -g  "$USER_NAME"  -G sudo  "$USER_NAME"  && \
    mkdir -p "/home/$USER_NAME" && \
    usermod -d "/home/$USER_NAME" "$USER_NAME"


USER $USER_NAME
WORKDIR /home/$USER_NAME
