FROM ubuntu:xenial
# ARG BRIDGE=false
# ARG INSTALL_TURTLEBOT2_DEMO_DEPS=false
# ARG PLATFORM=x86

ENV DEBIAN_FRONTEND noninteractive

RUN apt-get update && apt-get install --no-install-recommends -y locales
RUN locale-gen en_US.UTF-8
ENV LANG en_US.UTF-8

# net-tools is for ifconfig
# Get curl for fetching the repo keys.
# Get https transport for APT.
RUN apt-get update && apt-get install --no-install-recommends -y \
  lsb-release net-tools sudo \
  curl \
  apt-transport-https
