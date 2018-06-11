FROM {{ distro }}:{{ codename }}

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

RUN pip3 install catkin-tools

# RUN apt-get update && apt-get install --no-install-recommends -y \
#   lsb-release net-tools sudo
