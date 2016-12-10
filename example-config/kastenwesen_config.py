#!/usr/bin/python2.7
# -*- coding: utf-8 -*-

config_containers = []

disable_auto_upgrade = True

travis = False
if os.environ.get("TRAVIS"):
    print("\nHey Travis, nice to see you. I will progress slowly for you, so my tests won't fail.\n")
    travis = True
    STARTUP_GRACETIME = 5
    TCP_TIMEOUT = 20

#########################################
# my_linux_base                         #
# ===================================== #
# Linux (Ubuntu 14.04) base image       #
#########################################
# also available under the alias 'another-name:myversion'
my_linux_base = DockerContainer(name="my-linux-base", path="./my-linux-base/",
                                only_build=True,
                                alias_tags=["another-name:myversion"])
config_containers.append(my_linux_base)

# TODO dependency on my_linux_base, without linking

#########################################
# web                                   #
# ===================================== #
# A web server listening on port 80     #
#########################################
web = DockerContainer(name="webserver", path="./webserver/", sleep_before_test=2)
web.add_port(host_port=80, container_port=80)
web.add_volume(host_path=os.getcwd() + "/webserver/webroot",
               container_path="/var/www", readonly=True)
web.add_test(URLTest("http://localhost"))
config_containers.append(web)

#########################################
# test1                                 #
# ===================================== #
# A testserver listening on port 1231   #
#########################################
test1 = DockerContainer(name="test1", path="./test1/")
# this server doesn't answer with any data, so disable the test for the port
test1.add_port(host_port=1231, container_port=1234, test=False)
# some arbitrary shell tests
test1.add_test(DockerShellTest("true"))
# this test should fail with returncode 1
# test1.add_test(DockerShellTest("false"))
config_containers.append(test1)

#########################################
# test2                                 #
# ===================================== #
# A testserver listening on port 1232   #
# only listenining on localhost         #
# 20s extra startup gracetime           #
#########################################
test2 = DockerContainer(name="test2", path="./test2/", startup_gracetime=20)
test2.add_link(test1),
test2.add_port(host_addr="127.0.0.1", host_port=1232, container_port=1234)
# you can test the startup gracetime by adding this always-failing test.
# `kastenwesen status` will only return an error 20 seconds after starting the
# container, but not before.
# test2.add_test(DockerShellTest("false"))
config_containers.append(test2)

#########################################
# portforwarder_to_webserver            #
# ===================================== #
# A portforwarder that forwards the     #
# port 80 of webserver to 8080          #
# (reverse proxy on the TCP layer)      #
#########################################
portforwarder_to_web = DockerContainer(
    name="portforwarder-to-webserver",
    path="./portforwarder-to-webserver/"
)
portforwarder_to_web.add_port(host_port=8080, container_port=1234)
portforwarder_to_web.add_link(web)

config_containers.append(portforwarder_to_web)
