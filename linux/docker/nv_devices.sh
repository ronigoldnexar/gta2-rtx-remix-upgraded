#!/usr/bin/env bash
# nv_devices.sh [gpu]: prints the `--device` flags for the NVIDIA nodes of one GPU (index, default 0;
# "all" or a comma list also work), to pass next to `docker run --gpus`.
# Why: `docker update` (cpu_governor.sh moves the cpuset every minute) rewrites the cgroup-v2 device filter
# from Docker's own device list; the nodes the NVIDIA hook added for --gpus are not in it, so the driver's
# later re-open of /dev/nvidiaN fails with EPERM (Vulkan: "Failed to create fence", vkAllocateMemory errors;
# GL: lost context). Nodes passed with --device survive the update (commit 68bec1e, docs/remix-verify).
G=${1:-0}
if [ "$G" = all ]; then nodes=$(ls /dev/nvidia[0-9]* 2>/dev/null)
else nodes=$(for i in ${G//,/ }; do echo "/dev/nvidia${i#device=}"; done); fi
for n in $nodes /dev/nvidiactl /dev/nvidia-uvm /dev/nvidia-uvm-tools /dev/nvidia-modeset; do
  [ -e "$n" ] && printf -- '--device %s ' "$n"
done
