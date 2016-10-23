#!/bin/bash
set -x
# this is run on the VM to install docker and all dependencies of kastenwesen.py
sudo apt-get -q update
sudo apt-get -y -q install docker.io apparmor-profiles python-pip aha
sudo pip install -r requirements.txt
