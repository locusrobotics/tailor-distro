# packaging

Modern software packaging seems to exist along a continuum of isolation. At the far left, you have apt, which installs and runs software without any sort of isolation at all. On the far right is LXD, which has all the function of a VM hypervisor but using container technology

# Apt
- Seems pretty straighforward to build and bundle catkin and ament packages. Plenty of examples within ros_buildfarm, as a handy PoC with https://github.com/mikepurvis/ros-bundling

# snappy
- snappy isolates the install and runtime of your packages from the rest of the system. This is particularly useful for deploying on various OSes (although it's not super-well supported off Ubuntu), or running different applications in parallel without getting into dependency management.
- snappy plugins for catkin and ament exist, although they're relatively PoC level of maturity.
- snappy does not currently support using anything other than the ubuntu snap store to store and distribute your artifacts. This is some pretty heavy vendor lock-in
- if we want to use ubuntu-core instead of ubuntu, and go full-snap, we will have to repackage dependencies like redis, chrony, etc.

# flatpack
- flatpack is a lot less opinionated that snappy and supports most of the same paradigms, however it's to GUI apps and has dependencies on user sessions and dbus. the common opinion seems to be that flatpak is for GUIs and docker is for server apps.

# docker
- docker images, while not system images, tick a lot of our boxes. There's a ridiculous amount of tooling developed for docker
