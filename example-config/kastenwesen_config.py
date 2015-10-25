#!/usr/bin/python2.7
# -*- coding: utf-8 -*-

config_containers=[]
web = DockerContainer("webserver", "./webserver/", docker_options="-p 80:80 -v " + os.getcwd() + "/webserver/webroot:/var/www:ro", tests={'sleep_before':2, 'http_urls': ['http://localhost'], 'ports': [80]})
config_containers.append(web)
test1 = DockerContainer("test1", "./test1/", docker_options="-p 1231:1234", tests={'sleep_before':0, 'ports': [1231]})
config_containers.append(test1)
test2 = DockerContainer("test2", "./test2/", links=[test1], docker_options="-p 1232:1234", tests={'sleep_before':0, 'ports': [1232]})
config_containers.append(test2)
portforwarder_to_test2 = DockerContainer("portforwarder-to-test2", "./portforwarder-to-test2/", links=[test2], docker_options="-p 1337:1234", tests={'sleep_before':0, 'ports': [1337]})
config_containers.append(portforwarder_to_test2)