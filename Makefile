all: pep8 pylint build

build:
	skipper build

.DEFAULT:
	skipper -v $(MAKE) $@