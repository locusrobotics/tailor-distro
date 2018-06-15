#!/usr/bin/env sh
# Created by tailor-distro as workaround for https://github.com/colcon/colcon-ros/issues/16

if [ $# -eq 0 ] ; then
  /bin/echo "Usage: env.sh COMMANDS"
  /bin/echo "Calling env.sh without arguments is not supported anymore. Instead spawn a subshell and source a setup file manually."
  exit 1
fi

# ensure to not use different shell type which was set before
CATKIN_SHELL=sh

# source setup.sh from same directory as this file
_CATKIN_SETUP_DIR=$(cd "`dirname "$0"`" > /dev/null && pwd)
export ROS_WORKSPACE=$_CATKIN_SETUP_DIR
. "$_CATKIN_SETUP_DIR/setup.sh"
exec "$@"
