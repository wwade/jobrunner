FILES =
FILES += setup.py
FILES += jobrunner
FILES += test-docker.py

.PHONY: all
all: lint install check

.PHONY:
in-venv:
	test -n "$(VIRTUAL_ENV)"

.PHONY: lint
lint: in-venv
	isort -c --diff $(FILES)
	autopep8 --exit-code -ra --diff $(FILES)
	pylint -d fixme $(FILES)
	find jobrunner -type f -name "*.py" -not -name "compat.py" | xargs flake8 setup.py

.PHONY: install
install: in-venv
	pip show shell-jobrunner || pip install .

.PHONY: in-venv check
check: install
	pytest -v -l --junitxml=junit/test-results.xml --durations=10 jobrunner/

.PHONY: format
format: in-venv
	./format.sh
