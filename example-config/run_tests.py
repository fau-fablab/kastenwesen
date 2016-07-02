#!/usr/bin/env python2.7
import os
import subprocess
import logging
import time

script_dir = os.path.dirname(os.path.realpath(__file__))

travis = False
travis_sleeptime = 20  # seconds
if os.environ.get("TRAVIS"):
    print("\nOh hi Travis, how are you? I will go slowly on your machines in order to prevent failing tests.\n")
    travis = True

def assert_run_okay(cmd):
    kastenwesen_dir = script_dir + "/../"
    kastenwesen = kastenwesen_dir + "kastenwesen.py "
    cmd = kastenwesen + cmd
    logging.info(cmd)
    subprocess.check_call(cmd, shell=True)


def assert_run_fail(cmd):
    try:
        assert_run_okay(cmd)
    except subprocess.CalledProcessError:
        return
    raise Exception("command did not fail")

os.chdir(script_dir)

assert_run_fail("status")
assert_run_okay("rebuild")
assert_run_okay("status")
assert_run_okay("stop")
assert_run_fail("status")
assert_run_okay("restart")
if travis:
    time.sleep(travis_sleeptime)
assert_run_okay("status")
