#!/usr/bin/env python3

"""
Check if there are updates using the systems default package manager
"""

from __future__ import print_function
import sys

DISTRO_PM = None
try:
    import apt
    DISTRO_PM = 'apt'
except ImportError:
    pass
try:
    import yum
    DISTRO_PM = 'yum'
except ImportError:
    pass


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


def main(distro_pm):
    """
    check for updates with distro_pm and print them to stdout, errors to stderr
    """
    if distro_pm == 'apt':
        available_updates = apt_updates()
    elif distro_pm == 'yum':
        available_updates = yum_updates()
    else:
        _print_error("[!] This distro is not supported by check_for_update.")
    if available_updates:
        print(" ".join(available_updates))
    exit(0)


if __name__ == "__main__":
    main(DISTRO_PM)
