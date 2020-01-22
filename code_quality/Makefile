ROOT_DIR:=$(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
APP_DIR="${ROOT_DIR}/../app"
TESTS_DIR="${ROOT_DIR}/../tests"


.PHONY: h all flake pylint mypy coverage black low-hanging help

h: help

all: black flake mypy #pylint is broken, disabled for now

flake:
	flake8 --ignore=E731,W503,W504,E501,E265,C0301,W1202,W1203 --max-complexity 10 --exclude build,junk --exit-zero "${ROOT_DIR}/app"

pylint:
	pylint --exit-zero --rcfile pylintrc --output-format=colorized "${APP_DIR}"
	pylint --exit-zero --rcfile pylintrc --output-format=colorized "${TESTS_DIR}"

mypy:
	mypy --ignore-missing-imports "${APP_DIR}"
	mypy --ignore-missing-imports "${TESTS_DIR}"

black:
	black -l 88 -t py37 "${APP_DIR}"
	black -l 88 -t py37 "${TESTS_DIR}"

coverage:
	python -m pytest --junitxml=junit-results.xml --cov="${APP_DIR}" --cov-report=xml --cov-report=html unit

#	autopep8 -r -i -j 0 --max-line-length 999 -a -a -a ./

low-hanging:
	flake8 --select=F401 --max-complexity 10 --exclude build,junk --exit-zero "${APP_DIR}"
	flake8 --select=F403 --max-complexity 10 --exclude build,junk --exit-zero "${APP_DIR}"
	flake8 --select=F821 --max-complexity 10 --exclude build,junk --exit-zero "${APP_DIR}"
	flake8 --select=F841 --max-complexity 10 --exclude build,junk --exit-zero "${APP_DIR}"
	flake8 --select=W0107 --max-complexity 10 --exclude build,junk --exit-zero "${APP_DIR}"
	flake8 --select=W0706 --max-complexity 10 --exclude build,junk --exit-zero "${APP_DIR}"
	flake8 --select=W0105 --max-complexity 10 --exclude build,junk --exit-zero "${APP_DIR}"

############### Help ####################

help:
	@echo "#############################################"
	@echo "# This is a conveneince Makefile for Latigo #"
	@echo "#############################################"
	@echo ""
	@echo " Available targets:"
	@echo ""
	@echo " + make help          Show this help"
	@echo " + make all           Run all targets"
	@echo " + make flake         Run flake"
	@echo " + make mypy          Run mypy"
	@echo " + make pylint        Run pylint"
	@echo " + make coverage      Run coverage"
	@echo " + make black         Run black"
	@echo ""
