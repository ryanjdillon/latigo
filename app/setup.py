#!/usr/bin/env python

import os
from setuptools import setup, find_packages


setup_requirements = ["pytest-runner", "setuptools_scm"]


def read_file(fname):
    fn = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
    print(f"Reading from {fn}")
    if os.path.exists(fn):
        with open(fn) as f:
            return f.read()
    return ""


def remove_comment(line, sep="#"):
    i = line.find(sep)
    if i >= 0:
        line = line[:i]
    return line.strip()


def read_requirements_file(fname: str):
    fn = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
    print(f"Reading requirements from {fn}")
    lines = []
    with open(fn) as f:
        for r in f.readlines():
            r = r.strip()
            if len(r) < 1:
                continue
            r = remove_comment(r)
            if len(r) < 1:
                continue
            lines.append(r)
    return lines


setup(
    name="latigo",
    version=read_file("VERSION"),
    author="Lennart Rolland",
    author_email="lroll@equinor.com",
    description=(
        "A continuous prediction service that uses Gordo to predict data for IOC"
    ),
    license="AGPL-3.0",
    keywords="gordo ioc continuous prediction",
    url="https://github.com/equinor/latigo",
    packages=find_packages(),
    setup_requires=setup_requirements,
    zip_safe=True,
    long_description=read_file("README.md"),
    install_requires=read_requirements_file(
        "requirements.in"
    ),  # Allow flexible deps for install
    tests_require=read_requirements_file(
        "test_requirements.txt"
    ),  # Use rigid deps for testing
    test_suite="../tests",
    python_requires="~=3.7.4",
    include_package_data=True,
    # From https://pypi.org/pypi?%3Aaction=list_classifiers
    # fmt: off
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Other Audience",
        "Topic :: Utilities",
        "License :: OSI Approved :: GNU Affero General Public License v3",
        "Natural Language :: English",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3.7",
        "Topic :: Other/Nonlisted Topic"
    ],
    # fmt: on
)
