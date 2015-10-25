#!/usr/bin/python2.7
# -*- coding: utf-8 -*-

config_containers=[]
web = DockerContainer("webserver", "./webserver/", docker_options="-p 80:80", tests={'sleep_before':2, 'http_urls': ['http://localhost'], 'ports': [80]})
config_containers.append(web)
test1 = DockerContainer("test1", "./test1/", docker_options="-p 1234:1234", tests={'sleep_before':0, 'ports': [1234]})
config_containers.append(test1)
test2 = DockerContainer("test2", "./test2/", links=[test1], docker_options="-p 1235:1234", tests={'sleep_before':0, 'ports': [1235]})
config_containers.append(test2)