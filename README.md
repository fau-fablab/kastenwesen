# Kastenwesen ╰［°‿°］╯

[![Build Status](https://travis-ci.org/fau-fablab/kastenwesen.svg?branch=master)](https://travis-ci.org/fau-fablab/kastenwesen)

A python script for managing multiple docker containers on a server.

Imagine your server has multiple services that you want to separate and manage using docker.

- Set up a configuration that says how your docker containers should be linked, which ports should be exposed and which volumes should be used.
- Look at the status of your containers and services with ``kastenwesen status``. It also tells you if a container is running, but the service inside is not responding to TCP/HTTP requests.
- If you change something, just run ``kastenwesen rebuild``, lean back and wait until all containers have been rebuilt and then restarted.
- You still understand what this script is doing, because all executed docker commands are shown in the output. You could always run these yourself if something goes wrong.
- If there is a security update for a package that some of your containers depend on, simply run ``kastenwesen rebuild --no-cache``, so that docker's cache is not used and the fresh package is downloaded.

Even more is possible: You can use kastenwesen inside a VM, or even on travis.org, to test your server config before it goes live.

# Testing it inside a vagrant VM

If you don't want to run the commands on your PC, you can set up a VM. (Docker inside docker will usually not work if you have AppArmor etc. configured securely)
A bootstrapping script tested for Ubuntu 22 or Debian 12 is available at install_dependencies_ubuntu.sh . If you are using other distributions, please give feedback whether it works for you.

# Setting up a VM with vagrant:

You can also use vagrant + VirtualBox:
```
vagrant up
./kastenwesen_vagrant_wrapper.py [arguments]
```

More directly, you can also SSH into the target VM and execute kastenwesen commands there
```
vagrant ssh # connect into the machine
cd share # this is the same as this git folder

sudo -i
cd /home/vagrant/share/example-config
kastenwesen status
kastenwesen rebuild
curl localhost

```

# Continuous integration

For travis-ci, a demo .travis.yml file is provided. You at least want to run `kastenwesen rebuild` in your CI build.

Because of docker, the build needs root privilege. If you want to use Vagrant in a custom CI setup or for developer testing to ensure that your config is correct before going into production, a sample Vagrantfile and kastenwesen_vagrant_test_build.py build script are provided.

