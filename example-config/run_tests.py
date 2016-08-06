#!/usr/bin/env python2.7
import os
import subprocess
import logging
import time

script_dir = os.path.dirname(os.path.realpath(__file__))

travis = False
if os.environ.get("TRAVIS"):
    print("\nOh hi Travis, how are you? I will go slowly on your machines in order to prevent failing tests.\n")
    travis = True
    STARTUP_GRACETIME = 20
    TCP_TIMEOUT = 20


def diagnostics():
    # extra diagnostics output at each build step
    subprocess.check_call("pstree")
    subprocess.check_call("docker ps", shell=True)
    subprocess.check_call("date")
    if travis:
        time.sleep(STARTUP_GRACETIME)


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
except Exception as e:
    diagnostics()
    raise e
