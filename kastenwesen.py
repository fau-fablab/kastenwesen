#!/usr/bin/python2.7
# -*- coding: utf-8 -*-
"""kastenwesen: a python tool for managing multiple docker containers

Usage:
  kastenwesen help
  kastenwesen status [<container>...]
  kastenwesen rebuild [--no-cache] [<container>...]
  kastenwesen restart [<container>...]
  kastenwesen cleanup [--simulate] [--min-age=<days>]

Options:
  -v    enable verbose log output

Actions explained:
  status: show status
  rebuild: rebuild and restart

If the containers argument is not given, the command refers to all containers in the config.
"""

from __future__ import print_function
import docker
import sys
import logging
from time import sleep
import requests
import subprocess
import socket
import time
import datetime
from termcolor import colored, cprint
import os
from docopt import docopt
from fcntl import flock, LOCK_EX, LOCK_NB


def exec_verbose(cmd):
    """ run a command, and print infos about that to the terminal and log."""
    print(os.getcwd() + "$ " + colored(cmd, attrs=['bold']))
    subprocess.check_call(cmd, shell=True)

def print_success(text):
    logging.info(text)
    cprint(text, attrs=['bold'], color='green')

def print_warning(text):
    logging.warning(text)
    cprint(text, attrs=['bold'], color='red')

def print_fatal(text):
    logging.warning(text)
    cprint(text, attrs=['bold'], color='red')
    sys.exit(1)

def print_bold(text):
    logging.info(text)
    cprint(text, attrs=['bold'])


class AbstractContainer(object):
    pass

class DockerContainer(AbstractContainer):
    def __init__(self, name, path, docker_options="", links=None, tests=None):
        """
        :param options: commandline options to 'docker run'
        :param tests: dictionary {'sleep_before': <sleep time>, 'http': <list of http(s) URLs that must return HTTP OK>, 'port': <list of ports that must be listening>}
        """
        self.name = name
        self.image_name = self.name + ':latest'
        self.path = path
        self.docker_options = docker_options
        self.tests = tests if tests else {}
        self.links = links if links else []

    def __repr__(self):
        return '"name": "{name}", "image": "{image}"'.format(name=self.name, image=self.image_name)

    def rebuild(self, ignore_cache=False):
        """ rebuild the container image """
        # self.is_running() is called for the check against manually started containers from this image.
        # after building, the old images will be nameless and this check is no longer possible
        self.is_running()

        print_bold("rebuilding image " + self.image_name)
        nocache = "--no-cache" if ignore_cache else ""
        exec_verbose("docker build {nocache} -t {imagename} {path}".format(nocache=nocache, imagename=self.image_name, path=self.path))

    def running_container_id(self):
        """ return id of last known container instance, or False otherwise"""
        # the running id file is written by `docker run --cidfile <file>` in .start()
        try:
            f = open(self.name + '.running_container_id', 'r')
            return f.read()
        except IOError:
            return False

    def running_container_name(self):
        """ return name of last known container instance, or False otherwise"""
        try:
            f = open(self.name + '.running_container_name', 'r')
            return f.read()
        except IOError:
            return False

    def _set_running_container_name(self, new_id):
        previous_id = self.running_container_name()
        logging.debug("previous '{}' container name was: {}".format(self.name, previous_id))
        logging.debug("new '{}' container name is now: {}".format(self.name, new_id))
        f = open(self.name + '.running_container_name', 'w')
        f.write(new_id)
        f.close()

    def stop(self):
        running_id = self.running_container_name()
        print_bold("Stopping {name} container {container}".format(name=self.name, container=running_id))
        if running_id and self.is_running():
            exec_verbose("docker stop {id}".format(id=running_id))
        else:
            logging.info("no known instance running")

    def start(self):
        if self.is_running():
            raise Exception('container is already running')
        container_id_file = "{}.running_container_id".format(self.name)
        # move container id file out of the way if it exists - otherwise docker complains at startup
        try:
            os.rename(container_id_file, container_id_file + "_previous")
        except OSError:
            pass
        # names cannot be reused :( so we need to generate a new one each time
        new_name = self.name + datetime.datetime.now().strftime("-%Y-%m-%d_%H_%M_%S")
        docker_options = ""
        for linked_container in self.links:
            assert linked_container.is_running(), "linked container {} is not running".format(self.links)
            docker_options += "--link={name}:{alias} ".format(name=linked_container.running_container_name(), alias=linked_container.name)
        docker_options += self.docker_options
        cmdline = "docker run -d --memory=2g  --cidfile={container_id_file} --name={new_name} {docker_opts} {image_name} ".format(container_id_file=container_id_file, new_name=new_name, docker_opts=docker_options, image_name=self.image_name)
        print_bold("Starting container {}".format(new_name))
        logging.info("Starting {} container: {}".format(self.name, cmdline))
        #TODO volumes
        exec_verbose(cmdline)
        self._set_running_container_name(new_name)
        logging.debug("waiting 2s for startup")
        sleep(2)
        print("Log:")
        self.logs()

    def logs(self):
        print(api_client.logs(container=self.running_container_name(), stream=False))

    def follow_logs(self):
        try:
            for l in (api_client.logs(container=self.running_container_name(), stream=True, timestamps=True, stdout=True, stderr=True, tail=999)):
                print(l)
        except KeyboardInterrupt:
            sys.exit(0)

    def check_for_unmanaged_containers(self):
        """ warn if any containers not managed by kastenwesen are running from the same image """
        running_containers = api_client.containers()
        running_container_ids = [ container['Id'] for container in running_containers ]
        logging.debug("Running containers: " + str(running_container_ids))
        config_container_ids = [container.running_container_id() for container in CONFIG_CONTAINERS]

        # Check that no unmanaged containers are running from the same image
        for container in running_containers:
            if container['Image'] == self.image_name:
                if container['Id'] not in config_container_ids:
                    raise Exception("The container '{}', not managed by kastenwesen.py, is currently running from the same image '{}'. I am assuming this is not what you want. Please stop it yourself and restart it via kastenwesen. See the output of 'docker ps' for more info.".format(container['Id'], self.image_name))


    def is_running(self):
        self.check_for_unmanaged_containers()
        if not self.running_container_id():
            return False
        try:
            status = api_client.inspect_container(self.running_container_id())
            return status['State']['Running']
        except docker.errors.NotFound:
            return False


    def test(self, sleep_before=True):
        # check that the container is running
        if sleep_before:
            time.sleep(self.tests.get('sleep_before', 1))
        if not self.is_running():
            return False
        something_tested = False
        for url in self.tests.get('http_urls', []):
            something_tested = True
            try:
                t = requests.get(url)
                t.raise_for_status()
            except IOError:
                logging.warn("Test failed for HTTP {}".format(url))
                return False
        for obj in self.tests.get('ports', []):
            # obj may be a (host, port) tuple or just a port.
            if isinstance(obj, int):
                obj = ('localhost', obj)
            (host, port) = obj
            something_tested = True
            try:
                socket.create_connection((host, port), timeout=2)
            except IOError:
                logging.warn("Test failed for TCP host {} port {}".format(host, port))
                return False
        if not something_tested:
            logging.warn("no tests defined for container {}, a build error might go unnoticed!")
        return True

    def print_status(self, sleep_before=True):
        running = self.is_running()
        if not running:
            print_warning("{name}: container is stopped".format(name=self.name))
        if self.test(sleep_before):
            if running:
                print_success("{name} running, tests successful".format(name=self.name))
                return True
            else:
                print_warning("{name}: container is stopped, but tests are successful. WTF?".format(name=self.name))
        elif running:
            print_warning("{name} running, but tests failed".format(name=self.name))
        return False


def rebuild_many(containers, ignore_cache=False):
    for container in containers:
        container.rebuild(ignore_cache)
    # TODO dummy test before restarting real system
    restart_many(containers)

def restart_many(containers):
    # TODO also restart containers that are linked to the given ones - here and also at rebuild
    for container in containers:
        container.stop()
        container.start()
        container.print_status()

def status_many(containers):
    okay = True
    for container in containers:
        okay = container.print_status(sleep_before=False) and okay

def cleanup_containers(min_age_days=0, simulate=False):
    # TODO how to make sure this doesn't delete data-containers for use with --volumes-from?
    # -> only delete containers known to this script? that would require logging all previous IDs

    # get all non-running containers
    containers = api_client.containers(trunc=False, all=True)
    config_container_ids = [c.running_container_id() for c in CONFIG_CONTAINERS]
    for container in containers:
        if not (container['Status'].startswith('Exited') or container['Status'] == ''):
            # still running
            continue
        if container['Created'] > time.time() - 60*60*24*min_age_days:
            # TODO this filters by creation time, not stop time.
            # too young
            continue
        if container['Id'] in config_container_ids:
            print_warning("Not removing stopped container {} because it is the last known instance".format(container['Names']))
            # the last known instance is never removed, even if it was stopped ages ago
            continue
        if simulate:
            print_bold("would remove old container {name} with id {id}".format(name=container['Names'], id=container['Id']))
        else:
            print_bold("removing old container {name} with id {id}".format(name=container['Names'], id=container['Id']))
            exec_verbose("docker rm {id}".format(id=container['Id']))

def cleanup_images(min_age_days=0, simulate=False):
    """ remove all untagged images and all stopped containers older that were created more than N days ago"""

    images = api_client.images()
    # get all running and non-running containers
    containers = api_client.containers(all=True)
    # get the list of real ids -- image ids in .containers() are sometimes abbreviated
    used_image_ids = [api_client.inspect_container(container['Id'])['Image'] for container in containers]
    for image_id in used_image_ids:
        assert image_id in [img['Id'] for img in images], "Image does not exist"

    if simulate:
        print_warning("Warning: --simulate is not perfect: If containers are removed, their images might be removed too, but that is not shown in simulation")
    for image in images:
        if image['RepoTags'] != [u'<none>:<none>']:
            # image is tagged, skip
            continue
        if image['Id'] in used_image_ids:
            # image is in use, skip
            continue
        if image['Created'] > time.time() - 60*60*24*min_age_days:
            # image is too young, skip
            continue

        if simulate:
            print_bold("would delete unused old image {}".format(image['Id']))
        else:
            print_bold("deleting unused old image {}".format(image['Id']))
            exec_verbose("docker rmi " + image['Id'])

def check_config(containers):
    # containers may only link to ones that are before them in the list
    # otherwise the whole startup process doesnt work or links to the wrong ones

    for i in range(len(containers)):
        for link in containers[i].links:
            assert link in containers[0:i]

def main():
    arguments = docopt(__doc__, version='')

    loglevel = logging.INFO
    if "-v" in arguments:
        loglevel = logging.DEBUG
    logging.basicConfig(level=loglevel)


    # CONFIG
    # TODO outsorce to another file
    # A list of containers, ordered by dependency (e.g. database -> web application -> web application client, ...)
    # an image may only depend on images *before* it in the list
    # linking is also only allowed to containers *before* it in the list.

    # Lock against concurrent use
    lockfile = open("kastenwesen.lock", "w")
    try:
        flock(lockfile.fileno(), LOCK_EX | LOCK_NB)
    except IOError:
        print_fatal("Another instance is already running. Exiting")

    check_config(CONFIG_CONTAINERS)

    # parse common arguments
    given_containers = CONFIG_CONTAINERS
    if arguments["<container>"]:
        # use containers given on commandline containers, but keep the configuration order
        given_containers = [c for c in CONFIG_CONTAINERS if (c.name in arguments["<container>"])]
        if len(given_containers) != len(arguments["<container>"]):
            raise Exception("Unknown container name(s) given on commandline")

    if arguments["rebuild"]:
        rebuild_many(given_containers, ignore_cache=bool(arguments["--no-cache"]))
    elif arguments["restart"]:
        restart_many(given_containers)
    elif arguments["status"]:
        if status_many(given_containers):
            sys.exit(0)
        else:
            sys.exit(1)
    elif arguments["cleanup"]:
        if arguments["--min-age"] is None:
            min_age = 31
        else:
            min_age = int(arguments["--min-age"])
        cleanup_containers(min_age_days=min_age, simulate=arguments["--simulate"])
        cleanup_images(min_age_days=min_age, simulate=arguments["--simulate"])
    else:
        print(__doc__)

CONFIG_CONTAINERS = []
if __name__ == "__main__":
    # TODO hardcoded to the lower docker API version to run with ubuntu 14.04
    api_client = docker.Client(base_url='unix://var/run/docker.sock', version='1.12')
    try:
        config_containers = []
        # set config_containers from conf file
        execfile('kastenwesen_config.py')
        CONFIG_CONTAINERS = config_containers
    except IOError:
        print_fatal("No kastenwesen_config.py found in the current directory")
    main()

