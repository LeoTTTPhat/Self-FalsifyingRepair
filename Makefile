.PHONY: smoketest test

smoketest:
	python3 -m sfr.harness.smoketest

test:
	python3 -m unittest discover -s tests
