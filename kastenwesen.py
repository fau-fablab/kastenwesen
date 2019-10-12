#!/usr/bin/env python3
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
  kastenwesen status [<container>...] [--cron]
  kastenwesen (start|stop|restart) [--ignore-dependencies] [<container>...]
  kastenwesen rebuild [--no-cache] [--missing] [--ignore-dependencies] [<container>...]
  kastenwesen check-for-updates [--auto-upgrade] [<container>...]
  kastenwesen shell [--new-instance] <container>
  kastenwesen log [-f] <container>
  kastenwesen cleanup [--simulate] [--min-age=<days>]

Options:
  -v    enable verbose log output

Actions explained:
  status: show status
  start: inverse of stop.
            Due to the way how docker links work,
            some additional containers will automatically be restarted to fix links.
            If this is not possible, use --ignore-dependencies to suppress errors and bring up the container in a partly-working state.
  stop: stop a container or stop all containers.
            Also stops dependent containers
            (e.g. web application is stopped if you stop its database container)
            --ignore-dependencies: Don't stop dependent containers, but rather leave them in a partly-working state.
  restart: stop and start again
  rebuild: rebuild and restart.
            Takes care of dependencies.
            --no-cache: Force rebuild of all layers.
            --missing: skip images that are already built
  check-for-updates: Check if there are updates for this image
            --auto-upgrade: Also trigger a rebuild to apply these updates
            (auto-upgrade can be disabled by setting disable_auto_upgrade=True in kastenwesen_config)
  shell: exec a shell inside the running container,
            or inside a separate instance of this image if using --new-instance
  cleanup: carefully remove old containers and images that are no longer used

If the containers argument is not given, the command refers to all containers in the config.
"""

import datetime
import json
import logging
import os
import socket
import subprocess
import sys
import time
from collections import namedtuple
from copy import copy
from distutils.version import LooseVersion

import dateutil.parser
import docker
import requests
import termcolor
from docopt import docopt

from pidfilemanager import AlreadyRunning, PidFileManager

# switch off strange python requests warnings and log output
requests.packages.urllib3.disable_warnings()
REQUESTS_LOG = logging.getLogger("requests")
REQUESTS_LOG.setLevel(logging.WARNING)

# time to wait between starting containers and checking the status
DEFAULT_STARTUP_GRACETIME = 2

# default TCP timeout for tests
TCP_TIMEOUT = 2
HTTP_TIMEOUT = 5

SELINUX_STATUS = None

NAMESPACE = ''  # Namespace for containers and images. '' or '$namespace/'

# status files
STATUS_FILES_DIR = '/var/lib/kastenwesen/'
RUNNING_CONTAINER_NAME_FILE = STATUS_FILES_DIR + '%(name)s.running_container_name'
RUNNING_CONTAINER_ID_FILE = STATUS_FILES_DIR + '%(name)s.running_container_id'


class ContainerStatus(object):
    OKAY = "OKAY"
    FAILED = "FAILED"
    STARTING = "STARTING"
    MISSING = 'MISSING'


class ImageNotFound(Exception):
    """Exception if an image could not be found on the local machine."""
    def __init__(self, container):
        self.container = container
        super(ImageNotFound, self).__init__(
            'There is no image on the local machine for container {}. '
            'Maybe you have to build it first?'.format(self.container.name)
        )


def exec_verbose(cmd, return_output=False):
    """
    Run a command, and print infos about that to the terminal and log.

    :param bool return_output: return output as string, don't print it to the terminal.
    """
    print(os.getcwd() + "$ " + colored(cmd, attrs=['bold']), flush=True)
    if return_output:
        return subprocess.check_output(cmd, shell=True).decode('utf8')
    else:
        subprocess.check_call(cmd, shell=True)

def cprint(text, file=None, **options):
    """
    Print colored text for output on interactive terminals.

    Automatically disabled if the output is not a TTY.
    See ``termcolor.cprint`` for documentation on the parameters.
    """
    if file is None:
        file = sys.stdout
    if sys.stdout.isatty() and sys.stderr.isatty():
        termcolor.cprint(text, file=file, **options)
    else:
        print(text, file=file)

def colored(text, **options):
    """
    Color the text for output on interactive terminals.

    Automatically disabled if the output is not a TTY.
    See ``termcolor.colored`` for documentation on the parameters.
    """
    if sys.stdout.isatty() and sys.stderr.isatty():
        return termcolor.colored(text, **options)
    else:
        return text


def print_success(text):
    """Print positive information and success messages."""
    cprint(text, attrs=['bold'], color='green')


def print_notice(text):
    """Print information which is between good and bad, e.g. "container is still starting..."."""
    cprint(text, attrs=['bold'], color='yellow')


def print_warning(text):
    """Print negative information, errors, "container stopped", ... """
    cprint(text, attrs=['bold'], color='red', file=sys.stderr)


def print_fatal(text):
    """Print fatal errors and immediately exit."""
    cprint(text, attrs=['bold'], color='red', file=sys.stderr)
    sys.exit(1)


def print_bold(text):
    """Print neutral but important information."""
    cprint(text, attrs=['bold'])


def get_selinux_status():
    """:return: (disabled|permissive|enforcing)"""
    global SELINUX_STATUS
    if SELINUX_STATUS:
        return SELINUX_STATUS
    else:
        try:
            return subprocess.check_output(
                'getenforce 2>/dev/null || echo "disabled"',
                shell=True).decode('utf8').strip().lower()
        except subprocess.CalledProcessError as err:
            print_warning("Error while running 'getenforce' to get current SELinux status")
            logging.error(err)
            return 'disabled'


def docker_version_geq(version):
    """Return True, if the version of docker is at least `version`."""
    return LooseVersion(DOCKER_API_CLIENT.version()['Version']) >= version


class AbstractTest(object):
    def __call__(self, container_instance):
        """Run the test. May print error messages if something is not ok.

        :param container_instance: instance of the current container
        :rtype: bool
        :return: True if test successful, False otherwise.
        """
        return False


class HTTPTest(AbstractTest):
    def __init__(self, url, verify_ssl_cert=True, timeout=HTTP_TIMEOUT):
        self.timeout = timeout
        self.url = url
        self.verify_ssl_cert = verify_ssl_cert

    def __call__(self, container_instance):
        try:
            t = requests.get(self.url, verify=self.verify_ssl_cert, timeout=self.timeout)
            t.raise_for_status()
        except IOError as e:
            logging.error("Test failed for HTTP %s: %s", self.url, e)
            return False
        return True


class TCPPortTest(AbstractTest):
    def __init__(self, port, host=None, expect_data=True, timeout=TCP_TIMEOUT):
        self.timeout = timeout
        self.port = port
        self.host = host or 'localhost'
        self.expect_data = expect_data

    def __call__(self, container_instance):
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except IOError:
            logging.error("Connection failed for TCP host %s port %s", self.host, self.port)
            return False
        try:
            sock.settimeout(1)
            # send something
            sock.send(b'hello\n')
            # try to get a reply
            data = sock.recv(1)
            if not data:
                raise IOError("no response?")
        except IOError:
            logging.error(
                "No response from TCP host %s port %s - server dead "
                "or this protocol doesn't answer to a simple 'hello' packet.",
                self.host, self.port
            )
            return False
        return True


class DockerShellTest(AbstractTest):
    def __init__(self, shell_cmd, timeout=HTTP_TIMEOUT):
        """
        Test which runs a shell command with ``docker exec`` and tests for return value equal to zero.

        Only supported for docker containers.
        :param str shell_cmd:
            shell command for testing, e.g.
            ``hello | grep -q world``
            Will be interpreted by ``bash`` on the container.
        """
        assert isinstance(shell_cmd, str)
        self.shell_cmd = shell_cmd
        self.timeout = timeout

    def __call__(self, container_instance):
        """
        Run the test. See AbstractTest.run().

        :type container_instance: DockerContainer
        :return: status
        """
        assert isinstance(container_instance, DockerContainer)
        if not container_instance.is_running():
            return False
        cmd = ["docker", "exec", container_instance.running_container_name(),
               'bash', '-c', self.shell_cmd]
        try:
            subprocess.check_call(
                cmd,
                timeout=self.timeout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as err:
            logging.warning(
                "Test with shell command '%s' failed with returncode %s",
                self.shell_cmd, err.returncode,
            )
            return False
        except subprocess.TimeoutExpired as err:
            logging.warning(
                "Test with shell command '%s' timed out after %d seconds",
                self.shell_cmd, err.timeout,
            )
            return False
        return True


class AbstractContainer(object):
    def __init__(self, name, sleep_before_test=0.5, only_build=False, startup_gracetime=None):
        self.name = NAMESPACE + name
        self.tests = []
        self.links = []
        self.sleep_before_test = sleep_before_test
        if startup_gracetime is None:
            startup_gracetime = DEFAULT_STARTUP_GRACETIME
        self.startup_gracetime = startup_gracetime
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

    @property
    def is_built(self):
        """Return True if this container is already built or does not need to be built."""
        return True

    def time_running(self):
        """
        Time in seconds since last start/restart, or `None` if unsupported or temporarily not available.
        Test failures will be ignored if this runtime is shorter than a startup gracetime.

        :rtype: None | float
        """
        return None

    def test(self, sleep_before=True):
        """Return True if all tests succeeded."""
        success = True
        for test in self.tests:
            success = test(self) and success

        # check that the container is running
        if sleep_before:
            time.sleep(self.sleep_before_test)
        return success

    def get_status(self, sleep_before=True):
        """Return a tuple: (okay: ContainerStatus, msg: str)."""
        if not self.is_built:
            return (ContainerStatus.MISSING, 'image is missing on the local system')
        elif self.only_build and not self.tests:
            # no tests for build-only container -> always return OK
            return (ContainerStatus.OKAY, '(only build)')
        elif self.test(sleep_before):
            if self.is_running() or self.only_build:
                running = "running, " if self.is_running() else ""
                return (ContainerStatus.OKAY, '{message_run}{tests_ok}/{tests_ok} tests ok'.format(message_run=running, tests_ok=len(self.tests)))
            else:
                if self.tests:
                    return (ContainerStatus.FAILED, 'stopped, but tests succeeded. Check your tests!')
                else:
                    return (ContainerStatus.FAILED, 'stopped')
        else: # tests failed
            if self.only_build:
                return (ContainerStatus.FAILED, 'tests failed')
            if self.is_running():
                if self.time_running() < self.startup_gracetime:
                    return (ContainerStatus.STARTING, 'starting up... Tests not yet OK')
                else:
                    return (ContainerStatus.FAILED, 'running, but tests failed')
            else:
                return (ContainerStatus.FAILED, 'stopped')

    def needs_package_updates(self):
        """
        Run a check for package updates.

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
        Pseudo-'container' that only runs tests, nothing else.

        Can be used for monitoring external services from kastenwesen status.
        """
        AbstractContainer.__init__(self, name, only_build=True)


class DockerDatetime(object):
    def __init__(self, value):
        """
        Convert a datetime representation from the docker API into suitable python objects.

        Most functions take a ``default`` argument to control what is returned
        if the Docker API returns the pseudo-date ``0001-01-01T00:00:00Z``.

        :type value: int | str
        """
        if isinstance(value, int):
            self.date = datetime.datetime.utcfromtimestamp(value)
        elif value == "0001-01-01T00:00:00Z":
            self.date = None
        else:
            date = dateutil.parser.parse(value)
            # the returned timestamp is always UTC
            date = date.replace(tzinfo=None)
            self.date = date

    # We cannot subclass datetime because it cannot contain the special value ``None``,
    # but we try to be as transparent and similar as possible.

    def __bool__(self):
        """Evaluate as logical ``False`` if the Docker API returns the pseudo-date ``0001-01-01T00:00:00Z``."""
        return bool(self.date)

    def __str__(self):
        return str(self.date)

    # a few helpful functions

    def to_datetime(self, default=None):
        return self.date or default

    def timedelta_to_now(self, default=None):
        """Difference between the datetime and the system time.

        Positive if the date is in the past."""
        if self.date is None:
            return default
        else:
            return datetime.datetime.utcnow() - self.date

    def seconds_to_now(self, default=float('inf')):
        """Seconds between the datetime and the system time.

        Positive if the date is in the past."""
        delta = self.timedelta_to_now()
        if delta is None:
            return default
        else:
            return delta.total_seconds()


class DockerContainer(AbstractContainer):
    def __init__(self, name, path, docker_options="", sleep_before_test=0.5, only_build=False, alias_tags=None, startup_gracetime=None):
        """
        :param docker_options: commandline options to 'docker run'
        """
        AbstractContainer.__init__(self, name, sleep_before_test,
                                   only_build, startup_gracetime)
        self.image_name = self.name + ':latest'
        self.path = path
        self.docker_options = docker_options
        self.links = []
        self.alias_tags = alias_tags or []

    def add_link(self, link_to_container):
        """Add a link to the given container.

        The link alias will be the container name given in the config, so you can directly reach the container under its name."""
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
        Forward incoming connections on host_addr:host_post to container_port inside the container.

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

    def container_base_name(self):
        """Return the image name without namespace."""
        return self.name[len(NAMESPACE):]

    def rebuild(self, ignore_cache=False):
        """Rebuild the container image."""
        # self.is_running() is called for the check against manually started containers from this image.
        # after building, the old images will be nameless and this check is no longer possible
        self.is_running()

        print_bold("rebuilding image " + self.image_name)
        nocache = "--no-cache" if ignore_cache else ""
        exec_verbose("docker build {nocache} -t {imagename} {path}".format(nocache=nocache, imagename=self.image_name, path=self.path))
        # docker version < 1.10 needs '-f' argument to 'docker tag'
        # so that it works the way we expect it (overwrite tag if it exists)
        force_tag_argument = '' if docker_version_geq('1.10') else '-f'
        for tag in self.alias_tags:
            exec_verbose(
                "docker tag {force} {imagename} {tag}".format(
                    imagename=self.image_name, tag=tag,
                    force=force_tag_argument,
                )
            )

    def running_container_id(self):
        """Return id of last known container instance, or False otherwise"""
        # the running id file is written by `docker run --cidfile <file>` in .start()
        try:
            return open(
                RUNNING_CONTAINER_ID_FILE % {'name': self.container_base_name()}, 'r'
            ).read()
        except IOError:
            return False

    def running_container_name(self):
        """ return name of last known container instance, or False otherwise"""
        try:
            return open(
                RUNNING_CONTAINER_NAME_FILE % {'name': self.container_base_name()}, 'r'
            ).read()
        except IOError:
            return False

    def _set_running_container_name(self, new_id):
        previous_id = self.running_container_name()
        base_name = self.container_base_name()
        logging.debug("previous '%s' container name was: %s", base_name, previous_id)
        logging.debug("new '%s' container name is now: %s", base_name, new_id)
        open(RUNNING_CONTAINER_NAME_FILE % {'name': base_name}, 'w').write(new_id)

    def _get_docker_options(self):
        """Get all docker additional options like --link or custom options."""
        docker_options = ""
        for linked_container in self.links:
            if not linked_container.is_running():
                # linked container isn't running. This will only happen if startup of one container fails, or if --missing-dependencies is used.
                # FIXME: There is a race condition (time-of-check vs time-of-use) between .is_running() and the docker command execution-
                # If the container dies inbetween, the docker command will fail.
                print_warning(
                    "linked container {} is not running - container {} "
                    "will be missing this link until it is restarted!"
                    .format(linked_container.name, self.name)
                )
                continue
            docker_options += "--link={name}:{alias} ".format(name=linked_container.running_container_name(), alias=linked_container.name)
        docker_options += self.docker_options
        return docker_options


    def stop(self):
        """Stop the container."""
        running_id = self.running_container_name()
        print_bold("Stopping {name} container {container}".format(name=self.name, container=running_id))
        if running_id and self.is_running():
            exec_verbose("docker stop {id}".format(id=running_id))
        else:
            logging.info("no known instance running")

    def start(self):
        """Start the container."""
        if not self.is_built:
            raise ImageNotFound(container=self)
        if self.is_running():
            raise Exception('container is already running')
        base_name = self.container_base_name()
        container_id_file = RUNNING_CONTAINER_ID_FILE % {'name': base_name}
        # move container id file out of the way if it exists - otherwise docker complains at startup
        try:
            os.rename(container_id_file, container_id_file + "_previous")
        except OSError:
            pass
        # names cannot be reused :( so we need to generate a new one each time
        new_name = base_name + datetime.datetime.now().strftime("-%Y-%m-%d_%H_%M_%S")
        cmd = "docker run -d" \
            " --dns-search=." \
            " --memory=2g  --cidfile={container_id_file}" \
            " --name={new_name} {docker_options}" \
            " {image_name} ".format(
                container_id_file=container_id_file,
                new_name=new_name,
                docker_options=self._get_docker_options(),
                image_name=self.image_name,
            )
        print_bold("Starting container {}".format(new_name))
        exec_verbose(cmd)
        self._set_running_container_name(new_name)

    def logs(self, follow=False):
        MAX_LINES = 1000
        if not follow:
            out = DOCKER_API_CLIENT.logs(container=self.running_container_name(), stream=False, tail=MAX_LINES)
            lines = sum([1 for char in out if char == '\n'])
            if lines > MAX_LINES - 3:
                print_warning("Output is truncated, printing only the last {} lines".format(MAX_LINES))
            print(out.decode('utf8'))
        else:
            try:
                for l in DOCKER_API_CLIENT.logs(container=self.running_container_name(), stream=True, timestamps=True, stdout=True, stderr=True, tail=MAX_LINES):
                    print(l.decode('utf8'), end='')
            except KeyboardInterrupt:
                sys.exit(0)

    def check_for_unmanaged_containers(self):
        """ Warn if any containers not managed by kastenwesen are running from the same image."""
        config_container_ids = [
            container.running_container_id() for container in CONFIG_CONTAINERS
            if isinstance(container, DockerContainer)
        ]
        conflicting_containers = [
            container for container in DOCKER_API_CLIENT.containers()
            if container['Image'] == self.image_name
            and container['Id'] not in config_container_ids
            and not 'de.fau.fablab.kastenwesen.temporary' in container['Labels']
        ]
        logging.debug("Conflicting containers: %s", str(conflicting_containers))

        if conflicting_containers:
            container_list = '\n'.join((
                '- Container %s: Image %s' % (c['Id'][:12], c['Image'])
                for c in conflicting_containers
            ))
            raise Exception(
                "The following containers are not managed by kastenwesen.py, are currently running from kastenwesen images. "
                "I am assuming this is not what you want. "
                "Please stop it yourself and restart it via kastenwesen. "
                "See the output of 'docker ps' for more info.\n" + container_list
            )

    def is_running(self):
        """Return True if this container is running."""
        self.check_for_unmanaged_containers()
        if not self.running_container_id():
            return False
        try:
            status = DOCKER_API_CLIENT.inspect_container(self.running_container_id())
            return status['State']['Running']
        except (docker.errors.NotFound, docker.errors.NullResource):
            return False

    @property
    def is_built(self):
        """Return True if an image for this container exists locally."""
        return any(
            any(
                tag == self.name + (':latest' if ':' not in self.name else '')
                for tag in image['RepoTags']
            )
            for image in DOCKER_API_CLIENT.images(name=self.name)
        )

    def time_running(self):
        """
        Time in seconds since last start/restart, or `None` if unsupported or temporarily not available.
        Test failures will be ignored if this runtime is shorter than a startup gracetime.

        :rtype: None | float
        """
        if not self.running_container_id():
            return None
        try:
            status = DOCKER_API_CLIENT.inspect_container(self.running_container_id())
            return DockerDatetime(status['State']['StartedAt']).seconds_to_now()
        except docker.errors.NotFound:
            return None

    def needs_package_updates(self):
        """
        Run a check for package updates

        :return: ``True`` if any packages could be updated
        :rtype: bool
        """
        if not self.is_built:
            raise ImageNotFound(container=self)
        kastenwesen_path = os.path.dirname(os.path.realpath(__file__))

        if self.is_running():
            exec_verbose(
                "docker cp {kastenwesen_path}/helper/ {container}:/usr/local/".format(
                    container=self.running_container_name(),
                    kastenwesen_path=kastenwesen_path,
                )
            )
            cmd = "docker exec --user=root {container}" \
                " /usr/local/helper/python-wrapper.sh" \
                " /usr/local/helper/check_for_updates.py".format(
                    container=self.running_container_name(),
                )
        else:
            base_name = self.container_base_name()
            new_name = base_name + '-check-for-updates' + datetime.datetime.now().strftime("-%Y-%m-%d_%H_%M_%S")
            # run check_for_updates.py in a new container instance.

            # the temporary label is set so that check_for_unmanaged_containers()
            # does not complain about this "unmanaged" instance

            cmd = "docker run --rm" \
                " --dns-search=." \
                " --label de.fau.fablab.kastenwesen.temporary=True" \
                " --user=root" \
                " -v {kastenwesen_path}/helper/:/usr/local/kastenwesen_tmp/:ro{vol_opts}" \
                " --name={new_name} {docker_options}" \
                " {image_name}" \
                " /usr/local/kastenwesen_tmp/python-wrapper.sh" \
                " /usr/local/kastenwesen_tmp/check_for_updates.py".format(
                    new_name=new_name,
                    docker_options=self._get_docker_options(),
                    vol_opts=',Z' if get_selinux_status() == 'enforcing' else '',
                    kastenwesen_path=kastenwesen_path,
                    image_name=self.image_name,
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
            if not self.is_built:
                raise ImageNotFound(container=self)
            print("Starting a new container instance with an interactive shell:")
            base_name = self.container_base_name()
            new_name = base_name + '-tmp' + datetime.datetime.now().strftime("-%Y-%m-%d_%H_%M_%S")
            # the temporary label is set so that check_for_unmanaged_containers()
            # does not complain about this "unmanaged" instance
            cmd = "docker run --rm -it" \
                " --dns-search=." \
                " --label de.fau.fablab.kastenwesen.temporary=True" \
                " --name={new_name} {docker_options}" \
                " {image_name} bash".format(
                    new_name=new_name,
                    docker_options=self._get_docker_options(),
                    image_name=self.image_name,
                )
        else:
            # docker exec ... in running instance
            print("Starting a shell inside the running instance.")
            if not self.is_running():
                print_fatal("Container {} is not running. Use --new-instance to start a new container instance especially for the shell.".format(self.name))
            cmd = "docker exec -it {container} bash".format(container=self.running_container_name())
        exec_verbose(cmd)


def rebuild_many(containers, ignore_cache=False, only_missing=False, ignore_dependencies=False):
    """ rebuild given containers

    :param list[AbstractContainer] containers: containers to rebuild
    :param bool ignore_cache: use ``--no-cache`` in docker build to ensure that external dependencies are fresh
    :param bool only_missing: rebuild only containers if there is no image on the local system
    :param bool ignore_dependencies: do not stop/start dependent containers
    :return list[AbstractContainer]: all containers that were affected by the rebuild. Also contains additional dependent containers that had to be restarted.
    """
    for container in containers:
        if only_missing and container.is_built:
            logging.info("Skipping %s, because it is already built", container.name)
            continue
        container.rebuild(ignore_cache)
    return restart_many(containers, ignore_dependencies=ignore_dependencies)


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
                            logging.debug("Adding reverse dependency %s to the given list of containers", link)
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
                        logging.debug("Adding dependency %s to the given list of containers", link)
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


def restart_many(requested_containers, ignore_dependencies=False):
    """
    Restart given containers, and if necessary also their dependencies and reverse dependencies.

    :param list[AbstractContainer] requested_containers: containers to restart
    :param bool ignore_dependencies: do not stop/start dependent containers
    :return list[AbstractContainer]: all containers that were affected. Also contains additional dependent containers that had to be (re)started.
    """
    # also restart the containers that will be broken by this:
    stop_containers = stop_many(requested_containers, message_restart=True, ignore_dependencies=ignore_dependencies)

    start_containers = ordered_by_dependency(stop_containers, add_dependencies=True)
    added_dep_containers = [container for container in start_containers if container not in stop_containers]
    if added_dep_containers:
        print_bold(
            "Also starting necessary dependencies, if not yet running: {}".format(
                ", ".join([str(i) for i in added_dep_containers])
            )
        )

    for container in start_containers:
        if container.only_build:
            # container is only a meta container, not really started
            continue
        if container in stop_containers or not container.is_running():
            try:
                container.start()
            except ImageNotFound as exc:
                if ignore_dependencies:
                    print_warning("Ignoring missing dependency:")
                    print_warning(str(exc))
                else:
                    print_fatal(str(exc) + " Use --ignore-dependencies to skip this error.")
    return start_containers


def stop_many(requested_containers, message_restart=False, ignore_dependencies=False):
    """
    Stop the given containers and all that that depend on them (i.e. are linked to them)

    :param requested_containers: List of containers
    :type requested_containers: list[AbstractContainer]
    :param bool message_restart:
        Will the containers be restarted later?
        This only affects the log output, not the actions taken
    :param bool ignore_dependencies: do not stop/start dependent containers
    :rtype: list[AbstractContainer]
    :return: list of all containers that were stopped
             (includes the ones stopped because of dependencies)
    """

    stop_containers = list(reversed(ordered_by_dependency(requested_containers, add_reverse_dependencies=not ignore_dependencies)))
    added_dep_containers = [
        container for container in stop_containers
        if container not in requested_containers and container.is_running()
    ]
    if added_dep_containers:
        print_bold(
            "Also {verb} containers affected by this action: {containers}"
            .format(
                verb="restarting" if message_restart else "stopping",
                containers=", ".join([str(i) for i in added_dep_containers])
            )
        )
    for container in stop_containers:
        container.stop()
    return stop_containers


def need_package_updates(containers):
    """Return all of the given containers that need package updates."""
    try:
        return [container for container in containers if container.needs_package_updates()]
    except ImageNotFound as exc:
        print_fatal(str(exc))


def cleanup_containers(min_age_days=0, simulate=False):
    # TODO how to make sure this doesn't delete data-containers for use with --volumes-from?
    # -> only delete containers known to this script? that would require logging all previous IDs

    # get all non-running containers
    containers = DOCKER_API_CLIENT.containers(trunc=False, all=True)
    config_container_ids = [
        c.running_container_id() for c in CONFIG_CONTAINERS
        if isinstance(c, DockerContainer)
    ]
    removed_containers = []
    for container in containers:
        state = DOCKER_API_CLIENT.inspect_container(container['Id'])['State']
        if state['Running']:
            continue
        date_finished = DOCKER_API_CLIENT.inspect_container(container['Id'])['State']['FinishedAt']
        date_finished = DockerDatetime(date_finished)
        if date_finished:
            assert date_finished.to_datetime() > datetime.datetime(2002, 1, 1)
            if date_finished.timedelta_to_now() < datetime.timedelta(days=1) * min_age_days:
                # too young
                continue
            date_created = DockerDatetime(container['Created'])
            assert date_created.to_datetime() <= date_finished.to_datetime(), \
                "Container creation time is after the time it finished: " \
                "container='{}', parsed creation time={} --  state='{}' " \
                "parsed finishing time={}" \
                .format(container,
                        date_created,
                        DOCKER_API_CLIENT.inspect_container(container['Id'])['State'],
                        date_finished)
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

    images = DOCKER_API_CLIENT.images(all=True)
    # get all running and non-running containers
    containers = DOCKER_API_CLIENT.containers(all=True, trunc=False)
    # get the list of real ids -- image ids in .containers() are sometimes abbreviated
    used_image_ids = []
    for container in containers:
        used_image_id = DOCKER_API_CLIENT.inspect_container(container['Id'])['Image']
        assert used_image_id in [img['Id'] for img in images], "Image {img} does not exist, but is used by container {container}".format(img=used_image_id, container=container)
        if container['Id'] in simulated_deleted_containers:
            continue
        used_image_ids.append(used_image_id)

    dangling_images = DOCKER_API_CLIENT.images(filters={"dangling": True})
    for image in dangling_images:
        if image['RepoTags'] != ['<none>:<none>']:
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


def get_status(given_containers):
    """
    Return a list of named tuples containing the status of given_containers.

    >>> get_status(...)
    [(container_name, status, msg), ...]
    """
    StatusReport = namedtuple('StatusReport', ['container_name', 'status', 'msg'])
    return sorted([
        StatusReport(container.name, *container.get_status(sleep_before=False))
        for container in given_containers
    ], key=lambda x: str.lower(x.container_name))


def print_status_and_exit(given_containers, other_instance_running=False, out_format='ascii'):
    """
    Print container status to stdout and exit.

    out_format: 'ascii' for human readable text, 'json' for json on stdout
    Exit status:
        - 0: Everything ok
        - 1: There are failed containers
        - 42: There are failed containers but an other instance is running,
        too, which may cause the failures
    """
    try:
        status_report_list = get_status(given_containers)
    except docker.errors.APIError:
        if other_instance_running:
            print_warning("Cannot fetch the status, please try again later: \n"
                          "Ignoring a Docker internal API error because another kastenwesen instance is running. \n"
                          "(Docker API calls may fail if an image is being removed during the call.)")
            sys.exit(42)
        else:
            raise

    failed_containers = any(
        1 if status_report.status in (ContainerStatus.FAILED, ContainerStatus.MISSING) else 0
        for status_report in status_report_list
    )

    if out_format == 'ascii':
        for container_name, status, msg in status_report_list:
            if status == ContainerStatus.OKAY:
                print_success('[ ok ] {0}: {1}'.format(container_name, msg))
            elif status == ContainerStatus.STARTING:
                print_notice('[wait] {0}: {1}'.format(container_name, msg))
            elif status == ContainerStatus.FAILED:
                print_warning('[fail] {0}: {1}'.format(container_name, msg))
            elif status == ContainerStatus.MISSING:
                print_warning('[miss] {0}: {1}'.format(container_name, msg))
            else:
                raise ValueError('Invalid status {0} for {1}'.format(container_status, container_name))
    elif out_format == 'json':
        print(json.dumps(status_report_list))
    else:
        raise ValueError('Invalid format %s' % out_format)

    if failed_containers:
        if other_instance_running:
            if out_format == 'ascii':
                print_notice("Errors were ignored "
                             "because another kastenwesen instance is running.")
            sys.exit(42)
        else:
            if out_format == 'ascii':
                print_fatal("Some containers are not working!")

            sys.exit(1)

    sys.exit(0)


def check_config(containers):
    # containers may only link to ones that are before them in the list
    # otherwise the whole startup process doesnt work or links to the wrong ones

    for i, container in enumerate(containers):
        assert container not in containers[0:i], "container list contains a duplicate entry: {}".format(container)
        for link in container.links:
            assert link in containers[0:i], "containers may only link to containers defined before them"


def query_yes_no(question, default="yes"):
    """Ask a yes/no question via input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".

    Based on `code by Stackoverflow-user fmark<https://stackoverflow.com/a/3041990/4244236>`_.
    """
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        choice = input(question + prompt).lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            print("Please respond with 'yes' or 'no' (or 'y' or 'n').")


def main():
    arguments = docopt(__doc__, version='')

    logging.basicConfig(
        level=logging.DEBUG if '-v' in arguments else logging.INFO
    )

    # CONFIG
    # A list of containers, ordered by dependency (e.g. database -> web application -> web application client, ...)
    # an image may only depend on images *before* it in the list
    # linking is also only allowed to containers *before* it in the list.

    # read only args: "passive" actions which do not change containers
    # note: a running shell will crash on rebuilds of the same container!
    read_only_args = ["status", "log", "shell"]
    lock_needed = not any([arguments[key] for key in read_only_args])
    if arguments["check-for-updates"] and arguments["--auto-upgrade"]:
        lock_needed = True
    pid = PidFileManager("/var/lock/kastenwesen")
    other_instance_running = False
    if lock_needed:
        # Lock against concurrent use, except for readonly operations
        try:
            pid.lock()
        except AlreadyRunning as e:
            print_fatal(str(e))
    else:
        # readonly operations - print a warning if lockfile is still valid,
        # but continue nevertheless
        if pid.another_instance_is_running():
            other_instance_running = True
            print_warning("Another instance is already running: {}"
                          .format(pid.lockfile_information_str()))

    check_config(CONFIG_CONTAINERS)

    # parse common arguments
    given_containers = CONFIG_CONTAINERS
    if arguments["<container>"]:
        # use containers given on commandline containers, but keep the configuration order
        arg_containers_with_ns = [
            c if c.startswith(NAMESPACE) else NAMESPACE + c
            for c in arguments['<container>']
        ]
        given_containers = [
            c for c in CONFIG_CONTAINERS if c.name in arg_containers_with_ns
        ]
        if len(given_containers) != len(arguments["<container>"]):
            config_container_names = [c.name for c in CONFIG_CONTAINERS]
            unknown_containers = [
                c for c in arg_containers_with_ns
                if c not in config_container_names
            ]
            raise Exception(
                "Unknown container name(s) given on commandline: " +
                ', '.join(unknown_containers)
            )

    if arguments["rebuild"]:
        affected_containers = rebuild_many(given_containers, ignore_cache=bool(arguments["--no-cache"]), only_missing=bool(arguments["--missing"]), ignore_dependencies=bool(arguments["--ignore-dependencies"]))
        time.sleep(DEFAULT_STARTUP_GRACETIME)
        print_status_and_exit(affected_containers)
    elif arguments["restart"]:
        restart_many(given_containers, ignore_dependencies=bool(arguments["--ignore-dependencies"]))
        time.sleep(DEFAULT_STARTUP_GRACETIME)
        print_status_and_exit(given_containers)
    elif arguments["status"]:
        print_status_and_exit(
            given_containers,
            other_instance_running,
            out_format='json' if arguments['--cron'] else 'ascii',
        )
    elif arguments["start"]:
        restart_many([container for container in given_containers
                     if not (container.is_running() or container.only_build)],
                     ignore_dependencies=bool(arguments["--ignore-dependencies"]))
        time.sleep(DEFAULT_STARTUP_GRACETIME)
        print_status_and_exit(given_containers)
    elif arguments["stop"]:
        stop_many(given_containers, ignore_dependencies=bool(arguments["--ignore-dependencies"]))
    elif arguments["shell"]:
        try:
            given_containers[0].interactive_shell(arguments["--new-instance"])
        except ImageNotFound as exc:
            print_fatal(str(exc))
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
        print_bold("Checking containers for updates...")
        containers_with_updates = need_package_updates(given_containers)
        if not containers_with_updates:
            print_success("Packages are up to date.")
            sys.exit(0)
        containers_str = " ".join([cont.name for cont in containers_with_updates])
        if not arguments["--auto-upgrade"]:
            # only print output
            print_warning("Some containers have outdated packages: {}".format(containers_str))
            print_warning("Rebuild them with: kastenwesen check-for-updates --auto-upgrade\n"
                          "or: kastenwesen rebuild --no-cache {0}".format(containers_str))
            sys.exit(1)
        # auto upgrade:
        if arguments["--auto-upgrade"] and disable_auto_upgrade:
            if sys.__stdin__.isatty():
                query = query_yes_no("Auto-Upgrades are disabled by kastenwesen_config, "
                                     "do you want to upgrade nevertheless?", default="no")
                if not query:
                    print_bold("You selected not to auto-upgrade.")
                    sys.exit(1)
            else:
                print_bold("Auto-Upgrades are disabled by current kastenwesen_config!")
                sys.exit(1)
        print_bold("\n\nUpdating containers with outdated packages: {}\n".format(containers_str))
        time.sleep(2)  # some time to cancel
        affected_containers = rebuild_many(containers_with_updates, ignore_cache=True)
        print_status_and_exit(affected_containers)
    else:
        print(__doc__)

CONFIG_CONTAINERS = []
if __name__ == "__main__":
    # get config from current dir, or from /etc/kastenwesen
    if not os.path.isfile("./kastenwesen_config.py") and os.path.isdir("/etc/kastenwesen"):
        os.chdir("/etc/kastenwesen/")

    os.makedirs(STATUS_FILES_DIR, mode=0o755, exist_ok=True)

    # TODO hardcoded to the lower docker API version to run with ubuntu 14.04
    DOCKER_API_CLIENT = docker.Client(base_url='unix://var/run/docker.sock', version='1.12')
    if not os.path.isfile("kastenwesen_config.py"):
        print_fatal("No 'kastenwesen_config.py' found in the current directory or in '{0}'".format(os.getcwd()))

    config_containers = []
    disable_auto_upgrade = False
    # set config_containers from conf file
    with open("./kastenwesen_config.py", 'rb') as f:
        code = compile(f.read(), "./kastenwesen_config.py", 'exec')
        exec(code, globals(), locals())

    CONFIG_CONTAINERS = config_containers
    main()
