#!/bin/bash

# install dependencies, and setup kastenwesen

cd "$(dirname $0)"
./install_dependencies_ubuntu_14_04.sh
sudo ./setup.py install
ln -s `pwd`/ /opt/kastenwesen
ln -s `pwd`/cron.d_kastenwesen /etc/cron.d/kastenwesen
# This workaround is for testing on VirtualBox shared folders, where the files will be owned by someone else than root and then cron refuses to run
test -O /etc/cron.d/kastenwesen || { echo "Warning: kastenwesen dir not owned by root, working around this for cronjob"; rm /etc/cron.d/kastenwesen; cp `pwd`/cron.d_kastenwesen /etc/cron.d/kastenwesen; }
service cron reload
