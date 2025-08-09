#!/bin/bash
set -x
# this is run on the VM to install docker and all dependencies of kastenwesen.py
sudo apt-get -q update
sudo apt-get -y -q install docker.io apparmor-profiles python3-pip
# Install python dependencies using APT
sudo apt-get -y -q install python3-termcolor python3-docopt python3-docker python3-dateutil python3-packaging
# or from pip (does not work directly, needs an appropriate virtualenv set up)
# sudo pip3 install -r requirements.txt
