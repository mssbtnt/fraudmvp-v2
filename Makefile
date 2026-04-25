.PHONY: install redis api pipeline semakmule reddit test collect extract score alert

PYTHON ?= python3
VENV ?= .venv
PORT ?= 8000

install:
	$(PYTHON) -m venv $(VENV)
	. $(VENV)/bin/activate && $(PYTHON) -m pip install -r requirements.txt

redis:
	docker compose up -d redis

api:
	. $(VENV)/bin/activate && uvicorn api.main:app --host 0.0.0.0 --port $(PORT) --reload

pipeline:
	./fraud-mvp-daily-pipeline.sh

semakmule:
	./fraud-mvp-semakmule-sidecar.sh

reddit:
	./fraud-mvp-reddit-sidecar.sh

test:
	. $(VENV)/bin/activate && $(PYTHON) -m pytest tests

collect:
	. $(VENV)/bin/activate && $(PYTHON) -m agents.collector

extract:
	. $(VENV)/bin/activate && $(PYTHON) -m agents.extractor

score:
	. $(VENV)/bin/activate && $(PYTHON) -m agents.scorer

alert:
	. $(VENV)/bin/activate && $(PYTHON) -m agents.alerter
