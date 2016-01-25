#!/usr/bin/env python3
# simple wrapper that starts kastenwesen inside the vagrant container
# The config is expected to be in /home/vagrant/kastenwesen-config inside the VM.

# UNLICENSE
# (C) Max Gaukler 2016
import sys
import subprocess
sys.exit(subprocess.call("vagrant ssh -- cd /home/vagrant/kastenwesen-config; sudo kastenwesen".split(" ") + sys.argv[1:]))