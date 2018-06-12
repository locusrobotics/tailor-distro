# imaging

- In the style of embedded/IoT devices, we would like to be able to deploy our software in the form of images. Apt updates + ansible is error prone and leaves cruft from old deploys, i.e. it is not atomic.

- But docker/ubuntu-core/lxd/flatpak does atomic, do we still need imaging?
  - Yes. Even if our packaging of choice is _really_ good at consistent and atomic updates, being able to reimage a robot from scratch lets us change our minds later.
  - A project like snappy+ubuntu-core is fantastic and does 90% of what we want, however it is still very immature and vendor-locked. If Canonical drops development, we'd be holding the bag overnight.

## making images

Making a disk image carrying ubuntu + software + configuration is pretty straightforward. Lots of big projects already do this (docker, LXD), except ours are for bare metal.

- Make a bootable image with debootstrap
- Spin up the image with LXD/systemd-nspawn to make changes
- Install our packages
- Make our configuration changes
- update the machine hostname based on hardware ID. This can either:
  - be done by the out-of-date system, while deploying the update image to another partition
  - by the updated system, at firstboot

## deploying images

- Pull updated images down, with some sort of strategy to reduce traffic (cachine, delta images)
- Checksum/hash for consistency
- There's two primary partition schemes:
  - A mini /recovery OS that can burn an image on top of the /system partition
  - An A/B scheme where the primary and secondary partitions swap after applying the update
- Either approach requires programmatically updating the bootloader
- Writing the image to a partition can be done in a oneshot manner, or maybe we can apply 'updates' via block diffs.
- The image should be written to a read-only partition, so how do we handle the writeable part? One way is via and overlayfs

## Ostree + QtOta

- A lot of this is already done by the QtOta project, which builds on top of ostree tooling. We could use QtOta wholesale, or just take the parts we like and control ostree ourselves
  - looking over QtOta, it really doesn't do very much for us, other than having a very handy grub-config generation script and some C++ wrappers around ostree invocations. I would like to adapt that, and use ostree directly.
- ostree is basically a library for managing delta-updates for a sysroot.
- ostree keeps /etc/ and /var/ persistent, and throws away everything else between updates. This is probably acceptable to us.
  - https://ostree.readthedocs.io/en/latest/manual/adapting-existing/
