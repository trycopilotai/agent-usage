PYTHON ?= python3

.PHONY: help test check format demo assets collect report serve

help:
	@echo "test     run the suite"
	@echo "check    run the suite and the packaging assertions"
	@echo "format   apply the formatting codec"
	@echo "demo     regenerate the demo transcript"
	@echo "assets   regenerate the social preview"
	@echo "collect  read every provider and record the result"
	@echo "report   print the Markdown usage block"
	@echo "serve    serve the read only API on loopback"

test:
	$(PYTHON) -m pytest tests -q

check: test
	$(PYTHON) scripts/verify_demo.py
	$(PYTHON) scripts/generate_social_preview.py --check
	$(PYTHON) -m pytest tests/test_packaging.py -q
	git diff --check

assets:
	$(PYTHON) scripts/generate_social_preview.py

demo:
	sh scripts/demo.sh

format:
	$(PYTHON) -m black --line-length 100 agent_usage tests \
	  skills/agent-usage/run.py

collect:
	$(PYTHON) -m agent_usage.cli collect

report:
	$(PYTHON) -m agent_usage.cli report

serve:
	$(PYTHON) -m agent_usage.cli serve
