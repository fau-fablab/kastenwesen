#!/usr/bin/env python

"""
Check if there are updates using the systems default package manager

Note: this script should be compatible to python2 and 3.
"""

from __future__ import print_function
import sys
import os
import subprocess

EXTRA_UPDATE_CHECK_SCRIPT = '/check_extra_updates.sh'

PACKAGE_MANAGERS = []
try:
    import apt
    PACKAGE_MANAGERS.append('apt')
except ImportError:
    pass
try:
    import yum
    PACKAGE_MANAGERS.append('yum')
except ImportError:
    pass
if os.path.isfile(EXTRA_UPDATE_CHECK_SCRIPT):
    PACKAGE_MANAGERS.append('script')



def _print_error(msg):
    """print an error message to stderr and exit"""
    print(msg, file=sys.stderr)
    exit(1)


def apt_updates():
    """return a list of updates using apt"""
    # apt-get update

    cache = apt.Cache()
    try:
        cache.update()
    except apt.cache.LockFailedException:
        _print_error("Failed to get lock for apt-get update. Are you root?")
    except apt.cache.FetchFailedException:
        print("Warning: apt update failed, deleting cache and retrying...", file=sys.stderr)
        # NOTE: the following should suppress warnings/errors of apt-get update in dependent containers
        # because docker's overlayfs behaves weird on some operations
        # ("W: Problem unlinking the file /var/cache/apt/archives/partial/.apt-acquire-privs-test.Ccx1E4 - IsAccessibleBySandboxUser (13: Permission denied)")
        #, see :
        #   - https://github.com/moby/moby/issues/38076
        #   - https://docs.docker.com/storage/storagedriver/overlayfs-driver/#limitations-on-overlayfs-compatibility
        #   - related: https://bugzilla.redhat.com/show_bug.cgi?id=1213602#c11
        # This workaround causes apt update to always update every mirror.
        subprocess.check_call("rm -rf /var/lib/apt/lists".split(" "))
        subprocess.check_call("apt-get -q update".split(" "), stdout=sys.stderr)
        cache = apt.Cache()
        cache.update()

    # reload cache
    cache.close()
    cache.open()

    # apt-get dist-upgrade --dry-run
    cache.upgrade(dist_upgrade=True)
    available_updates = cache.get_changes()
    return [change.name for change in available_updates]


def yum_updates():
    """return a list of updates using yum"""
    base = yum.YumBase()
    tmp_stdout = sys.stdout
    sys.stdout = sys.stderr  # yum output to stderr
    available_updates = base.doPackageLists(
        pkgnarrow='updates',
        patterns='',
        ignore_case=True
    )
    sys.stdout = tmp_stdout
    return [package.name for package in available_updates]


def script_updates():
    """Run a custom script to check for updates."""
    output = subprocess.check_output(EXTRA_UPDATE_CHECK_SCRIPT).decode('utf8')
    return [line.strip() for line in output.splitlines() if line.strip()]


def main(package_managers):
    """Check for updates and print them to stdout, errors to stderr."""
    if not package_managers:
        _print_error("[!] This distro is not supported by check_for_update.")

    available_updates = []
    if 'apt' in package_managers:
        available_updates += apt_updates()
    if 'yum' in package_managers:
        available_updates += yum_updates()
    if 'script' in package_managers:
        available_updates += script_updates()

    if available_updates:
        print(" ".join(available_updates))
    exit(0)


if __name__ == "__main__":
    main(PACKAGE_MANAGERS)
