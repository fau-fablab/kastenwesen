#!/usr/bin/env python3
import os
import subprocess
import logging
import time

script_dir = os.path.dirname(os.path.realpath(__file__))

# extra sleep time in seconds. Must be higher than DEFAULT_STARTUP_GRACETIME. Some extra time can be helpful to work around race-condition bugs in the docker daemon.
EXTRA_SLEEP = 3

def diagnostics():
    # extra diagnostics output at each build step
    logging.debug("diagnostic output follows:")
    subprocess.check_call("pstree")
    subprocess.check_call("docker ps", shell=True)
    subprocess.check_call("date")
    time.sleep(EXTRA_SLEEP)


def assert_run_okay(cmd):
    kastenwesen_dir = script_dir + "/../"
    kastenwesen = kastenwesen_dir + "kastenwesen.py "
    cmd = kastenwesen + cmd
    logging.info(cmd)
    try:
        subprocess.check_call(cmd, shell=True)
    finally:
        diagnostics()


def assert_run_fail(cmd):
    try:
        assert_run_okay(cmd)
    except subprocess.CalledProcessError:
        return
    raise Exception("command did not fail")


logging.basicConfig(level=logging.DEBUG)
os.chdir(script_dir)

try:
    assert_run_fail("status")
    assert_run_okay("rebuild")
    assert_run_okay("status")
    assert_run_okay("stop")
    assert_run_fail("status")
    assert_run_okay("restart")
    assert_run_okay("status")
    assert_run_okay("check-for-updates")
    assert_run_okay("stop")
except Exception as e:
    diagnostics()
    raise e
