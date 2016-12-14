#!/bin/bash
set -x
# this is run on the VM to install docker and all dependencies of kastenwesen.py
sudo apt-get -q update
sudo apt-get -y -q install docker.io apparmor-profiles python3-pip aha
sudo pip3 install -r requirements.txt
