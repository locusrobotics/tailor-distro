FROM ubuntu:noble AS base

LABEL tailor="environment"

SHELL ["/bin/bash", "-c"]

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    PYTHONUNBUFFERED=1

ARG AWS_ACCESS_KEY_ID
ARG AWS_SECRET_ACCESS_KEY
ENV AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID} \
    AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}

ARG APT_REFRESH_KEY

RUN echo "APT refresh key=${APT_REFRESH_KEY}"
RUN sed -i 's/archive.ubuntu.com/us-east-1.ec2.&/g' /etc/apt/sources.list && \
    apt-get update && apt-get install --no-install-recommends -y \
    locales \
    curl \
    gnupg1 \
    sudo \
    bzip2 \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    python3-venv \
    git \
    ruby \
    ruby-bundler \
    vim \
    xz-utils && \
    locale-gen en_US.UTF-8 && \
    rm -rf /var/lib/apt/lists/*

# Install aptly for managing mirror debs
RUN curl -LO --output-dir /tmp https://github.com/aptly-dev/aptly/releases/download/v1.5.0/aptly_1.5.0_linux_amd64.tar.gz && \
    tar xzf /tmp/aptly_1.5.0_linux_amd64.tar.gz --strip-components 1 -C /usr/local/bin

FROM base AS debs3-build

WORKDIR /opt
# Install locusrobotics deb-s3 fork for managing bundle debs
RUN git clone -b master-noble https://github.com/locusrobotics/deb-s3.git && \
    cd deb-s3 && \
    bundle update --bundler && \
    bundle install

FROM base AS rosdep-tailor

# Create venv
RUN python3 -m venv /opt/tailor_venv

ENV VIRTUAL_ENV=/opt/tailor_venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip3 install \
    colcon-common-extensions \
    "git+https://github.com/ruffsl/colcon-cache.git"

COPY tailor-distro tailor-distro
RUN pip3 install -e tailor-distro

FROM base AS dev

ARG USER_NAME=tailor

# Copy the deb-s3 binary
COPY --from=debs3-build /opt/deb-s3 /opt/deb-s3
COPY --from=debs3-build /var/lib/gems /var/lib/gems
RUN ln -sf /opt/deb-s3/bin/deb-s3 /usr/local/bin/deb-s3

# Copy venv
COPY --from=rosdep-tailor /opt/tailor_venv /opt/tailor_venv
COPY --from=rosdep-tailor /tailor-distro /tailor-distro
ENV VIRTUAL_ENV=/opt/tailor_venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Inject the rosdep definitions from source
COPY rosdistro/rosdep/rosdep.yaml /etc/ros/rosdep/rosdep.yaml
RUN if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]] ; then rosdep init ; fi && \
     echo "yaml file:///etc/ros/rosdep/rosdep.yaml" > /etc/ros/rosdep/sources.list.d/10-tailor.list

RUN usermod -md "/home/$USER_NAME" -s /bin/bash -l $USER_NAME ubuntu && \
    groupmod -n $USER_NAME ubuntu && \
    echo "$USER_NAME:$USER_NAME" | chpasswd && \
    echo "$USER_NAME ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers

USER $USER_NAME
WORKDIR /home/$USER_NAME
RUN rosdep update
