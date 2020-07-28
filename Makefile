SERVICE := $(or ${SERVICE},quay.io/ocpmetal/ignition-manifests-and-kubeconfig-generate:latest)


all: pep8 pylint build

build:
	skipper build ignition-manifests-and-kubeconfig-generate

update: build
	GIT_REVISION=${GIT_REVISION} docker build --pull --build-arg GIT_REVISION -t $(SERVICE) -f Dockerfile.ignition-manifests-and-kubeconfig-generate .
	docker push $(SERVICE)

.DEFAULT:
	skipper -v $(MAKE) $@
