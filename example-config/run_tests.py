#!/usr/bin/env python2.7

"""
unit tests for kastenwesen
"""

import os
import subprocess
import logging

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))


def assert_run_okay(cmd):
    """runs kastenwesen {cmd} and fails, when the command fails"""
    kastenwesen = os.path.join(SCRIPT_DIR, '../kastenwesen/kastenwesen.py')
    cmd = '{kw} {cmd}'.format(kw=kastenwesen, cmd=cmd)
    logging.info(cmd)
    subprocess.check_call(cmd, shell=True)


def assert_run_fail(cmd):
    """runs kastenwesen {cmd} and fails, when the command succeeds"""
    try:
        assert_run_okay(cmd)
    except subprocess.CalledProcessError:
        return
    raise Exception("command did not fail")


if __name__ == "__main__":
    os.chdir(SCRIPT_DIR)

    assert_run_fail("status")
    assert_run_okay("rebuild")
    assert_run_okay("status")
    assert_run_okay("stop")
    assert_run_fail("status")
    assert_run_okay("restart")
    assert_run_okay("status")
