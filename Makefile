PY ?= python3

.PHONY: install run test lint docker clean

install:            ## create venv + install deps
	$(PY) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt

run:                ## start the app on :8000
	$(PY) server.py

test:               ## run the test suite
	$(PY) -m pytest tests/ -q

lint:               ## flake8
	$(PY) -m flake8 server.py tests/ --max-line-length=140

docker:             ## build + run via docker compose
	docker compose up --build

clean:              ## remove local python caches
	rm -rf .venv __pycache__ **/__pycache__ .pytest_cache
