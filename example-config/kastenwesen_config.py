#!/usr/bin/python2.7
# -*- coding: utf-8 -*-

config_containers = []

#########################################
# my_linux_base                         #
# ===================================== #
# Linux (Ubuntu 14.04) base image       #
#########################################
my_linux_base = DockerContainer(name="my-linux-base", path="./my-linux-base/")
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
config_containers.append(test1)

#########################################
# test2                                 #
# ===================================== #
# A testserver listening on port 1232   #
#########################################
test2 = DockerContainer(name="test2", path="./test2/")
test2.add_link(test1),
test2.add_port(host_port=1232, container_port=1234)
config_containers.append(test2)

#########################################
# portforwarder_to_test2                #
# ===================================== #
# A portforwarder that forwards the     #
# port of test2 to 1337                 #
# (like a reverse proxy)                #
#########################################
portforwarder_to_test2 = DockerContainer(name="portforwarder-to-test2",
                                         path="./portforwarder-to-test2/")
portforwarder_to_test2.add_port(host_port=1337, container_port=1234)
portforwarder_to_test2.add_link(test2)

config_containers.append(portforwarder_to_test2)
