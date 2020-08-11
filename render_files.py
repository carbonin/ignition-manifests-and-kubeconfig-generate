#!/usr/bin/env python

import argparse
import logging
import subprocess
from contextlib import contextmanager
import sys
import os
import shutil
import json
import yaml
import boto3
from botocore.exceptions import NoCredentialsError
import utils
import bmh_utils
import test_utils
import oc_utils

INSTALL_CONFIG = "install-config.yaml"
INSTALL_CONFIG_BACKUP = "backup-install-config.yaml"
SERVICE_CONFIG = "services-config.yaml"


def get_s3_client(s3_endpoint_url, aws_access_key_id, aws_secret_access_key):
    s3_client = boto3.client(
        's3',
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        endpoint_url=s3_endpoint_url
    )
    return s3_client


def upload_to_aws(s3_client, local_file, bucket, s3_file):
    try:
        s3_client.upload_file(local_file, bucket, s3_file, ExtraArgs={'ACL': 'public-read'})
        print("Upload Successful")
        return True
    except NoCredentialsError:
        print("Credentials not available")
        return False


def update_bmh_files(ignition_file, cluster_id, inventory_endpoint, token):
    try:
        if inventory_endpoint:
            hosts_list = utils.get_inventory_hosts(inventory_endpoint, cluster_id, token)
        else:
            logging.info("Using test data to get hosts list")
            hosts_list = test_utils.get_test_list_hosts(cluster_id)

        with open(ignition_file, "r") as file_obj:
            data = json.load(file_obj)
            storage_files = data['storage']['files']
            # since we don't remove file for now, we don't need to iterate through copy
            # for file_data in storage_files[:]:
            for file_data in storage_files:
                # if file_data['path'] == '/etc/motd':
                #    storage_files.remove(file_data)
                if bmh_utils.is_bmh_cr_file(file_data['path']):
                    bmh_utils.update_bmh_cr_file(file_data, hosts_list)

        with open(ignition_file, "w") as file_obj:
            json.dump(data, file_obj)
    except Exception as ex:
        raise Exception('Failed to update BMH CRs in bootstrap ignition, exception: {}'.format(ex))


def upload_to_s3(s3_endpoint_url, bucket, aws_access_key_id, aws_secret_access_key, install_dir, cluster_id):
    s3_client = get_s3_client(s3_endpoint_url, aws_access_key_id, aws_secret_access_key)
    prefix = cluster_id

    for root, _, files in os.walk(install_dir):
        for file_name in files:
            logging.info("Uploading file: %s", file_name)
            file_path = os.path.join(root, file_name)
            if file_name == "kubeconfig":
                file_name = "kubeconfig-noingress"
            s3_file_name = "{}/{}".format(prefix, file_name)
            print(s3_file_name)
            upload_to_aws(s3_client, file_path, bucket, s3_file_name)


def debug_print_upload_to_s3(install_dir):
    prefix = "dummy_cluster_id"
    for root, _, files in os.walk(install_dir):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            if file_name == "kubeconfig":
                file_name = "kubeconfig-noingress"
            s3_file_name = "{}/{}".format(prefix, file_name)
            print("Uploading file %s as object %s" % (file_path, s3_file_name))


@contextmanager
def backup_restore_install_config(config_dir):
    logging.info("Saving %s cause it will be deleted by installer", INSTALL_CONFIG)
    shutil.copyfile(os.path.join(config_dir, INSTALL_CONFIG), os.path.join(config_dir, INSTALL_CONFIG_BACKUP))
    yield
    logging.info("Restoring %s", INSTALL_CONFIG)
    shutil.move(os.path.join(config_dir, INSTALL_CONFIG_BACKUP), os.path.join(config_dir, INSTALL_CONFIG))


def generate_installation_files(work_dir, config_dir):
    with backup_restore_install_config(config_dir=config_dir):
        # [TODO] - uncomment this line when moving to 4.6, and comment the next one
        # command = "OPENSHIFT_INSTALL_INVOKER=\"assisted-installer\" %s/openshift-baremetal-install create ignition-configs --dir %s" \
        #        % (work_dir, config_dir)
        command = "OPENSHIFT_INSTALL_INVOKER=\"assisted-installer\" %s/openshift-install create " \
                  "ignition-configs --dir %s" % (work_dir, config_dir)
        try:
            logging.info("Generating installation files")
            subprocess.check_output(command, shell=True, stderr=sys.stdout)
        except Exception as ex:
            raise Exception('Failed to generate files, exception: {}'.format(ex))


def prepare_install_config(config_dir, install_config):
    install_config_path = os.path.join(config_dir, INSTALL_CONFIG)
    if not install_config and not os.path.exists(install_config_path):
        raise Exception("install config was not provided")

    if not os.path.exists(install_config_path):
        logging.info("writing install config to file")
        with open(os.path.join(config_dir, INSTALL_CONFIG), 'w+') as yaml_file:
            yaml_file.write(install_config)


def pull_secret(config_dir):
    with open(os.path.join(config_dir, INSTALL_CONFIG), 'r') as yaml_file:
        return yaml.safe_load(yaml_file)['pullSecret']


def set_pull_secret(config_dir):
    with open('/root/.docker/config.json', 'w+') as config_file:
        config_file.write(pull_secret(config_dir))


# def prepare_generation_data(work_dir, config_dir, install_config, openshift_release_image):
def prepare_generation_data(config_dir, install_config):
    prepare_install_config(config_dir, install_config)
    # set_pull_secret(config_dir)
    # [TODO] - remove comment after fixing subsystem
    # oc_utils.extract_baremetal_installer(work_dir, openshift_release_image)


def create_config_dir(work_dir):
    config_dir = os.path.join(work_dir, "installer_dir")
    subprocess.check_output(["mkdir", "-p", config_dir])
    return config_dir


def openshift_token(config_dir):
    secret = json.loads(pull_secret(config_dir))
    return secret["auths"]["cloud.openshift.com"]["auth"]


def create_services_config(work_dir, config_dir, openshift_release_image):
    mco_image = oc_utils.get_mco_image(work_dir, openshift_release_image)
    config_data = {'mco_image': mco_image}
    with open(os.path.join(config_dir, SERVICE_CONFIG), "w+") as yaml_file:
        yaml.dump(config_data, yaml_file)


def main():
    parser = argparse.ArgumentParser(description='Generate ignition manifest & kubeconfig')
    parser.add_argument('--s3_endpoint_url', help='s3 endpoint url', default=None)
    parser.add_argument('--s3_bucket', help='s3 bucket', default='test')
    args = parser.parse_args()

    work_dir = os.environ.get("WORK_DIR")
    install_config = os.environ.get("INSTALLER_CONFIG")
    cluster_id = os.environ.get("CLUSTER_ID")
    inventory_endpoint = os.environ.get("INVENTORY_ENDPOINT")
    s3_endpoint_url = os.environ.get("S3_ENDPOINT_URL", args.s3_endpoint_url)
    bucket = os.environ.get('S3_BUCKET', args.s3_bucket)
    aws_access_key_id = os.environ.get("aws_access_key_id", "accessKey1")
    aws_secret_access_key = os.environ.get("aws_secret_access_key", "verySecretKey1")
    # openshift_release_image = os.environ.get("OPENSHIFT_INSTALL_RELEASE_IMAGE_OVERRIDE")

    if not work_dir:
        raise Exception("working directory was not defined")

    # create configuration dir, contains install-config.yaml and generated files(ignitions, kubeconfig)
    config_dir = create_config_dir(work_dir=work_dir)

    # prepare all the data(files) needed by opeshift-installer
    # prepare_generation_data(work_dir, config_dir, install_config, openshift_release_image)
    prepare_generation_data(config_dir, install_config)

    # run openshift installer to produce ignitions and kubeconfig
    generate_installation_files(work_dir=work_dir, config_dir=config_dir)

    # create service config otput
    # [TODO] - remove after fixing subsystem
    # create_services_config(work_dir, config_dir, openshift_release_image)

    # update BMH configuration in boostrap ignition
    update_bmh_files("%s/bootstrap.ign" % config_dir, cluster_id, inventory_endpoint, openshift_token(config_dir))

    if s3_endpoint_url:
        upload_to_s3(s3_endpoint_url, bucket, aws_access_key_id, aws_secret_access_key, config_dir, cluster_id)
    else:
        # for debug purposes
        debug_print_upload_to_s3(config_dir)


if __name__ == "__main__":
    main()
