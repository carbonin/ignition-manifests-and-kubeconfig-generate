all: pep8 pylint build

build:
	skipper build ignition-manifests-and-kubeconfig-generate

.DEFAULT:
	skipper -v $(MAKE) $@