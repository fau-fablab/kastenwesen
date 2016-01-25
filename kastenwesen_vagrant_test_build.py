#!/usr/bin/env python3

# rebuild all containers
# to be run inside a VM or so

# UNLICENSE
# (C) Max Gaukler 2016
"""
kastenwesen_vagrant_test_build.py: starts a complete container rebuild inside vagrant, returns 0 if it worked, 1 otherwise.

The config is expected to be in /home/vagrant/kastenwesen-config inside the VM.

Usage: kastenwesen_vagrant_test_build.py [fast|clean]

Caching and build speed:
    clean: slowest build, even recreate the VM
    [default: keep VM, rebuild all containers]
    fast: enable caching, containers are only rebuilt if there were changes to the Dockerfile or its direct dependencies
"""


import sys
import subprocess


def run(cmd):
    print("Running: " + cmd)
    subprocess.check_call(cmd.split(" "))

args = sys.argv[1:]
fast_build = False
clean_vm = False
if args:
    if args == ["fast"]:
        fast_build = True
    elif args == ["clean"]:
        clean_vm = True
    if args != "fast":
        print(__doc__)
        sys.exit(1)

if clean_vm:
    run("vagrant halt")
    run("vagrant destroy -f")
run("vagrant up")
if fast_build:
    build_arg = ""
else:
    build_arg = " --no-cache"
run("./kastenwesen_vagrant_wrapper.py rebuild" + build_arg)
if not fast_build:
    run("vagrant halt")
print("\nRebuild successful :-)\n")
