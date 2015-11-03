FROM ubuntu:14.04
# update packages
RUN apt-get update && apt-get -y dist-upgrade && apt-get -y upgrade
# install dependencies of update check helper
RUN apt-get -y install python3 python3-apt
# basic tools like editor etc.
RUN apt-get -y install curl wget nano
RUN apt-get clean

# fake command that never exits
# TODO can be removed as soon as not-running 'template containers' are supported
CMD sleep 999999999999999d
