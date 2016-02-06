#!/usr/bin/env python

"""
install kastenwesen
"""

from setuptools import setup, find_packages
import os
import kastenwesen
import subprocess


def read(fname):
    """returns the text of a file"""
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


def get_requirements(filename="requirements.txt"):
    """returns a list of all requirements"""
    text = read(filename)
    requirements = []
    for line in text.split('\n'):
        req = line.split('#')[0].strip()
        if req != '':
            requirements.append(req)
    return requirements


def get_version():
    """
    returns a version string which is either the current tag or commit hash
    """
    version = subprocess.check_output("git tag -l --contains HEAD", shell=True)
    if version.strip() == '':
        version = subprocess.check_output(
            "git log -n1 --abbrev-commit --format=%h", shell=True)
    return version.strip()

if __name__ == "__main__":
    setup(
        name="kastenwesen",
        packages=find_packages(),
        entry_points={
            "console_scripts": [
                "kastenwesen = kastenwesen.__main__:main"
            ]
        },
        author=kastenwesen.__authors__,
        license=kastenwesen.__license__,
        description=kastenwesen.__doc__,
        long_description=read("README.md"),
        url=kastenwesen.__url__,
        version=get_version(),
        install_requires=get_requirements(),
        classifiers=[
            'Environment :: Console',
            'Intended Audience :: System Administrators',
            'Operating System :: POSIX',
            'Programming Language :: Python',
        ],
    )
