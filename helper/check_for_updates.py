#!/usr/bin/env python3
import apt
import sys
cache = apt.Cache()
try:
    cache.update()
except apt.cache.LockFailedException:
    sys.stderr.write("Failed to get lock for apt-get update. Are you root?\n")
    sys.exit(1)
# this only simulates a dist-upgrade:
cache.upgrade(dist_upgrade=True)
changes = cache.get_changes()
if changes:
    print(" ".join([change.name for change in changes]))
sys.exit(0)
