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
import os


def run(cmd, may_fail=False):
    """
    Run command, print info, check return status

    :param list[basestring] cmd:  given as list of strings, one item per argument
    :param bool may_fail: if ``False`` (default), raise ``subprocess.CalledProcessError`` on failure instead of returning ``False``.
    :return: ``True`` on success, ``False`` otherwise.
    :rtype: bool
    """
    print("Running: " + " ".join(cmd))
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        if may_fail:
            return False
        else:
            raise e
    return True

args = sys.argv[1:]
fast_build = False
clean_vm = False
if args:
    if args == ["fast"]:
        fast_build = True
    elif args == ["clean"]:
        clean_vm = True
    else:
        print(__doc__)
        sys.exit(1)

if clean_vm:
    run("vagrant halt".split(" "))
    run("vagrant destroy -f".split(" "))
# call "vagrant up" if VM is not yet running
if "running" not in str(subprocess.check_output("vagrant status".split(" "))):
    run("vagrant up".split(" "))
if fast_build:
    build_arg = []
else:
    build_arg = ["--no-cache"]
okay = run([os.path.dirname(os.path.realpath(__file__)) + "/kastenwesen_vagrant_wrapper.py", "rebuild"] + build_arg, may_fail=True)
if not okay:
    print("\n ERROR! \n")
    sys.exit(1)
if not fast_build:
    run("vagrant halt".split(" "))
print("\nRebuild successful :-)\n")
