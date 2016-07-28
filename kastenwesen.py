#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
#
# kastenwesen: a python tool for managing multiple docker containers
#
# Copyright (C) 2016 kastenwesen contributors [see git log]
# https://github.com/fau-fablab/kastenwesen
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


"""
kastenwesen: a python tool for managing multiple docker containers

Usage:
  kastenwesen [help]
  kastenwesen (status|start|restart|stop) [<container>...]
  kastenwesen rebuild [--no-cache] [<container>...]
  kastenwesen check-for-updates [<container>...]
  kastenwesen shell [--new-instance] <container>
  kastenwesen log [-f] <container>
  kastenwesen cleanup [--simulate] [--min-age=<days>]

Options:
  -v    enable verbose log output

Actions explained:
  status: show status
  rebuild: rebuild and restart. Takes care of dependencies.
  stop: stop a container or stop all containers. Also stops dependent containers (e.g. web application is stopped if you stop its database container)
  start: inverse of stop. Due to the way how docker links work, some additional containers will automatically be restarted to fix links.
  restart: stop and start again
  shell: exec a shell inside the running container, or inside a separate instance of this image if using --new-instance
  cleanup: carefully remove old containers and images that are no longer used

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
import dateutil.parser
from termcolor import colored, cprint
import os
from docopt import docopt
from fcntl import flock, LOCK_EX, LOCK_NB
from copy import copy

# switch off strange python requests warnings and log output
requests.packages.urllib3.disable_warnings()
requests_log = logging.getLogger("requests")
requests_log.setLevel(logging.WARNING)

# time to wait between starting containers and checking the status
STARTUP_GRACETIME = 2

# workaround to always flush the output buffer
real_print = print


def print(s):
    real_print(s)
    sys.stderr.flush()
    sys.stdout.flush()


def exec_verbose(cmd, return_output=False):
    """
    run a command, and print infos about that to the terminal and log.

    :param bool return_output: return output as string, don't print it to the terminal.
    """
    print(os.getcwd() + "$ " + colored(cmd, attrs=['bold']))
    if return_output:
        return subprocess.check_output(cmd, shell=True)
    else:
        subprocess.check_call(cmd, shell=True)


def print_success(text):
    cprint(text, attrs=['bold'], color='green')


def print_warning(text):
    cprint(text, attrs=['bold'], color='red', file=sys.stderr)


def print_fatal(text):
    cprint(text, attrs=['bold'], color='red', file=sys.stderr)
    sys.exit(1)


def print_bold(text):
    cprint(text, attrs=['bold'])


def get_selinux_status():
    """:return: (disabled|permissive|enforcing)"""
    try:
        return subprocess.check_output(
            'getenforce 2>/dev/null || echo "disabled"',
            shell=True).strip().lower()
    except subprocess.CalledProcessError as e:
        print_warning("Error while running 'getenforce' to get current SELinux status")
        print(e)
        return 'disabled'


class AbstractTest(object):
    def run(self, container_instance):
        """ run the test. May print error messages if something is not right.

        :param container_instance: instance of the current container
        :rtype: bool
        :return: True if test successful, False otherwise.
        """
        return False


class URLTest(AbstractTest):
    def __init__(self, url, verify_ssl_cert=True):
        self.url = url
        self.verify_ssl_cert = verify_ssl_cert

    def run(self, container_instance):
        try:
            t = requests.get(self.url, verify=self.verify_ssl_cert)
            t.raise_for_status()
        except IOError, e:
            logging.error("Test failed for HTTP {}: {}".format(self.url, e))
            return False
        return True


class TCPPortTest(AbstractTest):
    def __init__(self, port, host=None, expect_data=True):
        self.port = port
        self.host = host or 'localhost'
        self.expect_data = expect_data

    def run(self, container_instance):
        try:
            sock = socket.create_connection((self.host, self.port), timeout=2)
        except IOError:
            logging.error("Connection failed for TCP host {} port {}".format(self.host, self.port))
            return False
        try:
            sock.settimeout(1)
            # send something
            sock.send("hello\n")
            # try to get a reply
            data = sock.recv(1)
            if not data:
                raise IOError("no response?")
        except IOError:
            logging.error("No response from TCP host {} port {} - server dead "
                         "or this protocol doesn't answer to a simple 'hello' "
                         "packet.".format(self.host, self.port))
            return False
        return True


class DockerShellTest(AbstractTest):
    def __init__(self, shell_cmd):
        """
        Test which runs a shell command with ``docker exec`` and tests for return value equal to zero.
        Only supported for docker containers.

        :param str shell_cmd:
            shell command for testing, e.g.
            ``hello | grep -q world``
            Will be interpreted by ``bash`` on the container.
        """
        assert isinstance(shell_cmd, basestring)
        self.shell_cmd = shell_cmd

    def run(self, container_instance):
        """
        run the test. See AbstractTest.run()

        :type container_instance: DockerContainer
        :return: status
        """
        assert isinstance(container_instance, DockerContainer)
        if not container_instance.is_running():
            return False
        cmd = ["docker", "exec", container_instance.running_container_name(),
               'bash', '-c', self.shell_cmd]
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError as e:
            logging.warn("Test with shell command '{command}' failed with returncode {returncode}".format(
                command=self.shell_cmd,
                returncode=e.returncode
            ))
            return False
        return True


class AbstractContainer(object):
    def __init__(self, name, sleep_before_test=0.5, only_build=False):
        self.name = name
        self.tests = []
        self.links = []
        self.sleep_before_test = sleep_before_test
        self.only_build = only_build

    def add_test(self, test):
        assert isinstance(test, AbstractTest), "given test must be a AbstractTest subclass"
        self.tests.append(test)

    def stop(self):
        pass

    def start(self):
        pass

    def rebuild(self, ignore_cache=False):
        pass

    def is_running(self):
        return False

    def test(self, sleep_before=True):
        if not self.tests:
            logging.warn("no tests defined for container {}, a build error might go unnoticed!".format(self.name))
        success = True
        for test in self.tests:
            success = test.run(self) and success

        # check that the container is running
        if sleep_before:
            time.sleep(self.sleep_before_test)
        return success

    def print_status(self, sleep_before=True):
        if self.only_build:
            if self.tests:
                if not self.test(sleep_before):
                    print_warning("{name}: tests failed".format(name=self.name))
                    return False
                else:
                    print_success("{}: tests OK".format(self.name))
                    return True
            else:
                print_success("{} (only build)".format(self.name))
                return True
        running = self.is_running()
        if not running:
            print_warning("{name}: container is stopped".format(name=self.name))
        if self.test(sleep_before):
            if running:
                print_success("{name} running, tests OK".format(name=self.name))
                return True
            else:
                print_warning("{name}: container is stopped, but tests are successful. WTF?".format(name=self.name))
        elif running:
            print_warning("{name} running, but tests failed".format(name=self.name))
        return False

    def needs_package_updates(self):
        """
        Run a check for package updates

        :return: ``True`` if any packages could be updated
        :rtype: bool
        """
        return False


class CustomBuildscriptTask(AbstractContainer):
    def __init__(self, name, build_command):
        """
        Run a custom build script for a build-only container.

        The environment variable IGNORE_CACHE is set to 0/1 depending on the use of --no-cache in 'kastenwesen rebuild'.
        """
        AbstractContainer.__init__(self, name, only_build=True)
        self.build_command = build_command

    def rebuild(self, ignore_cache=False):
        # TODO handle ignore_cache
        exec_verbose("IGNORE_CACHE={} ".format(int(ignore_cache)) + self.build_command)


class MonitoringTask(AbstractContainer):
    def __init__(self, name):
        """
        pseudo-'container' that only runs tests, nothing else. Can be used for monitoring external services from kastenwesen status.
        """
        AbstractContainer.__init__(self, name, only_build=True)


class DockerContainer(AbstractContainer):
    def __init__(self, name, path, docker_options="", sleep_before_test=0.5, only_build=False, alias_tags=None):

        """
        :param docker_options: commandline options to 'docker run'
        """
        AbstractContainer.__init__(self, name, sleep_before_test, only_build)
        self.image_name = self.name + ':latest'
        self.path = path
        self.docker_options = docker_options
        self.links = []
        self.alias_tags = alias_tags or []

    def add_link(self, link_to_container):
        """Add a link to the given container. The link alias will be the container name given in the config, so you can directly reach the container under its name."""
        assert isinstance(link_to_container, DockerContainer)
        self.links.append(link_to_container)

    def add_volume(self, host_path, container_path, readonly=False):
        assert os.path.exists(host_path), "volume path {p} doesn't exist".format(p=host_path)
        vol = [host_path, container_path]
        options = []
        if readonly:
            options.append('ro')
        if get_selinux_status() == 'enforcing':
            options.append('Z')
        if options:
            vol.append(','.join(options))
        self.docker_options += " -v {0}  ".format(':'.join(vol))

    def add_port(self, host_port, container_port, host_addr=None, test=True, udp=False):
        """
        forward incoming connections on host_addr:host_post to container_port inside the container.

        :param boolean test:
            test for an open TCP server on the port, raise error if nothing is listening there.
            Parameter is ignored for UDP.

        :param host_addr: host IP (or name) to listen on, or ``None`` to listen on all interfaces
        :type host_addr: str | None
        :param boolean udp: use UDP instead of TCP.
        """
        if host_addr:
            self.docker_options += " -p {host_addr}:{host_port}:{container_port}".format(host_port=host_port, container_port=container_port, host_addr=host_addr)
        else:
            self.docker_options += " -p {host_port}:{container_port}".format(host_port=host_port, container_port=container_port)

        if udp:
            self.docker_options += "/udp"

        if test:
            self.add_test(TCPPortTest(port=host_port, host=host_addr))

    def __str__(self):
        return self.name

    def rebuild(self, ignore_cache=False):
        """ rebuild the container image """
        # self.is_running() is called for the check against manually started containers from this image.
        # after building, the old images will be nameless and this check is no longer possible
        self.is_running()

        print_bold("rebuilding image " + self.image_name)
        nocache = "--no-cache" if ignore_cache else ""
        exec_verbose("docker build {nocache} -t {imagename} {path}".format(nocache=nocache, imagename=self.image_name, path=self.path))
        for tag in self.alias_tags:
            exec_verbose("docker tag -f {imagename} {tag}".format(imagename=self.image_name, tag=tag))

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
            if not linked_container.is_running():
                # linked container isn't running. This will only happen if startup of one container fails.
                print_warning("linked container {} is not running - container {} "
                              "will be missing this link until being restarted!"
                              .format(linked_container.name, self.name))
                continue
            docker_options += "--link={name}:{alias} ".format(name=linked_container.running_container_name(), alias=linked_container.name)
        docker_options += self.docker_options
        cmdline = "docker run -d --memory=2g  --cidfile={container_id_file} --name={new_name} {docker_opts} {image_name} ".format(container_id_file=container_id_file, new_name=new_name, docker_opts=docker_options, image_name=self.image_name)
        print_bold("Starting container {}".format(new_name))
        logging.info("Starting {} container: {}".format(self.name, cmdline))
        exec_verbose(cmdline)
        self._set_running_container_name(new_name)

    def logs(self, follow=False):
        MAX_LINES = 1000
        if not follow:
            out = api_client.logs(container=self.running_container_name(), stream=False, tail=MAX_LINES)
            lines = sum([1 for char in out if char == '\n'])
            if lines > MAX_LINES - 3:
                print_warning("Output is truncated, printing only the last {} lines".format(MAX_LINES))
            sys.stdout.write(out)
        else:
            try:
                for l in (api_client.logs(container=self.running_container_name(), stream=True, timestamps=True, stdout=True, stderr=True, tail=MAX_LINES)):
                    sys.stdout.write(l)
            except KeyboardInterrupt:
                sys.exit(0)

    def check_for_unmanaged_containers(self):
        """ warn if any containers not managed by kastenwesen are running from the same image """
        running_containers = api_client.containers()
        running_container_ids = [container['Id'] for container in running_containers]
        logging.debug("Running containers: " + str(running_container_ids))
        config_container_ids = [container.running_container_id() for container in CONFIG_CONTAINERS if isinstance(container, DockerContainer)]

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

    def needs_package_updates(self):
        kastenwesen_path = os.path.dirname(os.path.realpath(__file__))
        cmd = "docker run --rm --user=root -v {kastenwesen_path}/helper/:/usr/local/kastenwesen_tmp/:ro{vol_opts} {image} /usr/local/kastenwesen_tmp/python-wrapper.sh /usr/local/kastenwesen_tmp/check_for_updates.py 2>/dev/null".format(
            vol_opts=',Z' if get_selinux_status() == 'enforcing' else '',
            image=self.image_name,
            kastenwesen_path=kastenwesen_path,
        )
        updates = exec_verbose(cmd, return_output=True)
        if updates:
            print_warning("Container {} has outdated packages: {}".format(self.name, updates))
            return True
        else:
            return False

    def interactive_shell(self, new_instance=False):
        """
        start a shell inside the running instance using ``docker exec``

        :param bool new_instance:
            start the shell in a separate container instance
            using ``docker run``,
            do not start it in the already running container.
        """

        if new_instance:
            # docker run ... to launch new instance
            print("Starting a new container instance with an interactive shell:")
            cmd = "docker run -it {container} bash".format(container=self.name)
        else:
            # docker exec ... in running instance
            print("Starting a shell inside the running instance.")
            if not self.is_running():
                print_fatal("Container {} is not running. Use --new-instance to start a new container instance especially for the shell.")
            cmd = "docker exec -it {container} bash".format(container=self.running_container_name())
        exec_verbose(cmd)


def rebuild_many(containers, ignore_cache=False):
    for container in containers:
        container.rebuild(ignore_cache)
    # TODO dummy test before restarting real system
    restart_many(containers)


def ordered_by_dependency(containers, add_dependencies=False, add_reverse_dependencies=False):
    """ Sort and possibly enlarge the list of containers so that it can be used for starting/stopping a group of containers without breaking any links.

    The list will be given in an order in which they can be started. Reverse it for stopping.

    :param bool add_dependencies: Add any containers that the given ones depend on. (useful for starting)
    :param bool add_reverse_dependencies: Add any containers that depend on the given ones. (useful for stopping)
    """

    containers = list(containers)
    if add_reverse_dependencies:
        reverse_dependencies = set(containers)
        something_changed = True
        while something_changed:
            # loop through all links, looking for something that can be directly or indirectly broken by stopping one of the given containers
            something_changed = False
            for container in config_containers:
                for link in container.links:
                    if link in containers or link in reverse_dependencies:
                        # stopping the given list will break this container
                        if container in reverse_dependencies:
                            # already added, skip this one
                            continue
                        else:
                            something_changed = True
                            logging.debug("Adding reverse dependency {} to the given list of containers".format(link))
                            reverse_dependencies.add(container)
        containers += list(reverse_dependencies)
    ordered_containers = []
    something_changed = True
    while something_changed:
        something_changed = False
        for container in copy(containers):
            if container in ordered_containers:
                # already added, skip this one
                continue
            links_satisfied = True
            for link in container.links:
                if link not in containers:
                    # this container links to a container not given in the list
                    if add_dependencies:
                        logging.debug("Adding dependency {} to the given list of containers".format(link))
                        containers.append(link)
                        something_changed = True
                    else:
                        # this dependency cannot be satisfied, ignore.
                        continue
                if link not in ordered_containers:
                    links_satisfied = False
            if links_satisfied:
                ordered_containers.append(container)
                something_changed = True
    return ordered_containers


def restart_many(requested_containers):
    # also restart the containers that will be broken by this:
    stop_containers = stop_many(requested_containers, message_restart=True)

    start_containers = ordered_by_dependency(stop_containers, add_dependencies=True)
    added_dep_containers = [container for container in start_containers if container not in stop_containers]
    if added_dep_containers:
            print_bold("Also starting necessary dependencies, if not yet running: {}".format(", ".join([str(i) for i in added_dep_containers])))

    for container in start_containers:
        if container.only_build:
            # container is only a meta container, not really started
            continue
        if container in stop_containers or not container.is_running():
            container.start()


def stop_many(requested_containers, message_restart=False):
    """
    Stop the given containers and all that that depend on them (i.e. are linked to them)

    :param containers: List of containers
    :type containers: list[AbstractContainer]
    :rtype: list[AbstractContainer]
    :return: list of all containers that were stopped
             (includes the ones stopped because of dependencies)

    :param bool message_restart:
        Will the containers be restarted later?
        This only affects the log output, not the actions taken
    """

    stop_containers = list(reversed(ordered_by_dependency(requested_containers, add_reverse_dependencies=True)))
    added_dep_containers = [container for container in stop_containers
                            if (container not in requested_containers and container.is_running())]
    if added_dep_containers:
            print_bold("Also {verb} containers affected by this action: {containers}"
                       .format(verb="restarting" if message_restart else "stopping",
                               containers=", ".join([str(i) for i in added_dep_containers])))
    for container in stop_containers:
        container.stop()
    return stop_containers


def status_many(containers):
    okay = True
    for container in containers:
        container_okay = container.print_status(sleep_before=False)
        okay = container_okay and okay
    return okay


def need_package_updates(containers):
    """ return all of the given containers that need package updates """
    return [container for container in containers if container.needs_package_updates()]


def cleanup_containers(min_age_days=0, simulate=False):
    # TODO how to make sure this doesn't delete data-containers for use with --volumes-from?
    # -> only delete containers known to this script? that would require logging all previous IDs

    # get all non-running containers
    containers = api_client.containers(trunc=False, all=True)
    config_container_ids = [c.running_container_id() for c in CONFIG_CONTAINERS \
                            if isinstance(c, DockerContainer)]
    removed_containers = []
    for container in containers:
        state = api_client.inspect_container(container['Id'])['State']
        if state['Running']:
            continue
        date_finished = api_client.inspect_container(container['Id'])['State']['FinishedAt']
        if date_finished == "0001-01-01T00:00:00Z":
            date_finished = None
        else:
            date_finished = dateutil.parser.parse(date_finished)
            date_finished = date_finished.replace(tzinfo=None)  # the returned timestamp is always UTC
        now = datetime.datetime.utcnow()
        if date_finished:
            assert date_finished > datetime.datetime(2002, 01, 01)
            if date_finished > now - datetime.timedelta(days=1)*min_age_days:
                # too young
                continue
            date_created = datetime.datetime.utcfromtimestamp(container['Created'])
            date_created = date_created.replace(tzinfo=None)  # the result is always UTC
            assert date_created <= date_finished, "Container creation time is after the time it finished: container='{}', parsed creation time={} --  state='{}'  parsed finishing time={}".format(container, datetime.datetime.fromtimestamp(container['Created']), api_client.inspect_container(container['Id'])['State'], date_finished)
        if container['Id'] in config_container_ids:
            print_warning("Not removing stopped container {} because it is the last known instance".format(container['Names']))
            # the last known instance is never removed, even if it was stopped ages ago
            continue
        removed_containers.append(container['Id'])
        if simulate:
            print_bold("would remove old container {name} with id {id}".format(name=container['Names'], id=container['Id']))
        else:
            print_bold("removing old container {name} with id {id}".format(name=container['Names'], id=container['Id']))
            exec_verbose("docker rm {id}".format(id=container['Id']))
    return removed_containers


def cleanup_images(min_age_days=0, simulate=False, simulated_deleted_containers=None):
    """ remove all untagged images and all stopped containers older that were created more than N days ago"""

    if not simulated_deleted_containers:
        simulated_deleted_containers = []

    images = api_client.images(all=True)
    # get all running and non-running containers
    containers = api_client.containers(all=True, trunc=False)
    # get the list of real ids -- image ids in .containers() are sometimes abbreviated
    used_image_ids = []
    for container in containers:
        used_image_id = api_client.inspect_container(container['Id'])['Image']
        assert used_image_id in [img['Id'] for img in images], "Image {img} does not exist, but is used by container {container}".format(img=used_image_id, container=container)
        if container['Id'] in simulated_deleted_containers:
            continue
        used_image_ids.append(used_image_id)

    dangling_images = api_client.images(filters={"dangling": True})
    for image in dangling_images:
        if image['RepoTags'] != [u'<none>:<none>']:
            # image is tagged, skip
            raise Exception("this should not happen, as we filtered for dangling images only")
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
            try:
                exec_verbose("docker rmi --no-prune=true " + image['Id'])
            except subprocess.CalledProcessError:
                print_warning("Failed to remove unused image {}".format(image['Id']))


def print_status_and_exit(given_containers):
    if status_many(given_containers):
        print_success("Success.")
        sys.exit(0)
    else:
        print_fatal("Some containers are not working!")
        sys.exit(1)


def check_config(containers):
    # containers may only link to ones that are before them in the list
    # otherwise the whole startup process doesnt work or links to the wrong ones

    for i in range(len(containers)):
        assert containers[i] not in containers[0:i], "container list contains a duplicate entry: {}".format(containers[i])
        for link in containers[i].links:
            assert link in containers[0:i], "containers may only link to containers defined before them"


def main():
    arguments = docopt(__doc__, version='')

    loglevel = logging.INFO
    if "-v" in arguments:
        loglevel = logging.DEBUG
    logging.basicConfig(level=loglevel)

    # CONFIG
    # A list of containers, ordered by dependency (e.g. database -> web application -> web application client, ...)
    # an image may only depend on images *before* it in the list
    # linking is also only allowed to containers *before* it in the list.

    read_only_args = ["status", "check-for-updates", "log"]
    lock_needed = not sum([arguments[key] for key in read_only_args])
    if lock_needed:
        # Lock against concurrent use, except for readonly operations
        try:
            lockfile = open("/var/lock/kastenwesen.lock", "w")
        except IOError:
            print_fatal("Cannot acquire lock. Are you root?")
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
        print_status_and_exit(given_containers)
    elif arguments["restart"]:
        restart_many(given_containers)
        time.sleep(STARTUP_GRACETIME)
        print_status_and_exit(given_containers)
    elif arguments["status"]:
        print_status_and_exit(given_containers)
    elif arguments["start"]:
        restart_many(container for container in given_containers
                     if not (container.is_running() or container.only_build))
        time.sleep(STARTUP_GRACETIME)
        print_status_and_exit(given_containers)
    elif arguments["stop"]:
        stop_many(given_containers)
    elif arguments["shell"]:
        given_containers[0].interactive_shell(arguments["--new-instance"])
    elif arguments["log"]:
        given_containers[0].logs(follow=arguments["-f"])
    elif arguments["cleanup"]:
        if arguments["--min-age"] is None:
            min_age = 31
        else:
            min_age = int(arguments["--min-age"])
        deleted_containers = cleanup_containers(min_age_days=min_age, simulate=arguments["--simulate"])
        simulated_deleted_containers = []
        # if simulating, pass on the information about deleted containers for
        # correct simulation results
        if arguments["--simulate"]:
            simulated_deleted_containers = deleted_containers
        cleanup_images(min_age_days=min_age,
                       simulate=arguments["--simulate"],
                       simulated_deleted_containers=simulated_deleted_containers)
    elif arguments["check-for-updates"]:
        containers_with_updates = need_package_updates(given_containers)
        if containers_with_updates:
            containers_str = " ".join([cont.name for cont in containers_with_updates])
            print_warning("Some containers have outdated packages: {}".format(containers_str))
            print_warning("Rebuild them with: kastenwesen rebuild --no-cache {}".format(containers_str))
            sys.exit(1)
        else:
            print_success("Packages are up to date.")
            sys.exit(0)
    else:
        print(__doc__)

CONFIG_CONTAINERS = []
if __name__ == "__main__":
    # get config from current dir, or from /etc/kastenwesen
    if not os.path.isfile("./kastenwesen_config.py") and os.path.isdir("/etc/kastenwesen"):
        os.chdir("/etc/kastenwesen/")
    # TODO hardcoded to the lower docker API version to run with ubuntu 14.04
    api_client = docker.Client(base_url='unix://var/run/docker.sock', version='1.12')
    if not os.path.isfile("kastenwesen_config.py"):
        print_fatal("No 'kastenwesen_config.py' found in the current directory or in '{0}'".format(os.getcwd()))
    config_containers = []
    # set config_containers from conf file
    execfile('kastenwesen_config.py')
    CONFIG_CONTAINERS = config_containers
    if get_selinux_status() == 'enforcing':
        print_bold("SELinux status is 'enforcing'")
    main()
