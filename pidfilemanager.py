#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# kastenwesen: a python tool for managing multiple docker containers
#
# Copyright (C) 2016 kastenwesen contributors [see git log]
# https://github.com/fau-fablab/kastenwesen
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


"""
pidfilemanager: Lockfile / PID-file manager
which also allows to probe the lock without acquiring it.
Linux only as it relies on /proc.
"""

import logging
import os
from fcntl import flock, LOCK_EX, LOCK_NB


class AlreadyRunning(Exception):
    def __init__(self, message):
        msg = "Another instance is already running: {0}"
        super(AlreadyRunning, self).__init__(msg.format(message))


class PidFileManager(object):
    """
    Lockfile / PID file handling to check for or lock against concurrently
    running instances.

    For 'write' operations requiring lock, use :meth:`lock`.

    To give a warning during 'read' operations, check with
    :meth:`another_instance_is_running` and get human-readable information
    about the instance that acquired the lock with
    :meth:`lockfile_information_str`.
    """

    def __init__(self, filename):
        """
        PID file handling. Initialising does not yet lock!

        After locking, do not discard the class instance because this can cause
        unlocking.
        """
        self.filename = filename
        self.cmdline_filename = filename + ".cmdline"
        try:
            # open the file in append-mode because we want to read the content
            # and later erase it, but also creat the file if it doesnt exist
            self.lockfile = open(self.filename, "a+")
            self.lockfile.seek(0)
            try:
                self.old_pid = int(self.lockfile.read())
            except ValueError:
                self.old_pid = -1
                self.old_cmdline = "<unknown>"
                logging.warn("Cannot parse lockfile contents - expected PID")
        except IOError:
            raise Exception("Cannot open lockfile.")

        if self.old_pid != -1:
            # read cmdline only if a valid PID was found.
            # this is done to allow a seamless transition
            # from other locking schemes which may have created the pidfile
            try:
                    with open(self.cmdline_filename, "r") as f:
                        self.old_cmdline = f.read()
            except IOError:
                raise Exception("Cannot open cmdline lockfile")

    def another_instance_is_running(self):
        """
        Query whether the instance that called :meth:`lock` is still alive.
        """
        try:
            cmdline = open("/proc/{}/cmdline".format(self.old_pid)).read()
            # PID still exists, check whether it is the right cmdline,
            # or it was just reused for another process
            return (cmdline == self.old_cmdline)
        except IOError:
            # PID doesn't exist anymore
            return False

    def lockfile_information_str(self):
        """
        Return human-readable information about the locking instance.
        This only makes sense if :meth:`another_instance_is_running` returns
        ``True``.
        """
        return "PID {0}: {1}".format(self.old_pid,
                                     self.old_cmdline.replace('\0', ' '))

    def lock(self):
        """
        Lock, or raise an exception if already locked.

        :raise: AlreadyRunning
        :rtype: None
        """
        if self.another_instance_is_running():
            raise AlreadyRunning(self.lockfile_information_str())
        try:
            flock(self.lockfile.fileno(), LOCK_EX | LOCK_NB)
        except IOError:
            raise Exception("cannot lock lockfile, although it seems "
                            "that no instance is already running")
        # clear lockfile contents, write new content
        self.lockfile.seek(0)
        self.lockfile.truncate()
        self.lockfile.write(str(os.getpid()))
        self.lockfile.flush()
        with open(self.cmdline_filename, "w") as f:
            cmdline = open("/proc/self/cmdline").read()
            f.write(cmdline)
            f.close()
