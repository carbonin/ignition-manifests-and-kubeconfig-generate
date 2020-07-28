#!/usr/bin/env python

import argparse
import logging
import subprocess
import sys
import os
import shutil
import json
import boto3
from botocore.exceptions import NoCredentialsError
import utils
import bmh_utils
import test_utils

INSTALL_CONFIG = "install-config.yaml"
INSTALL_CONFIG_BACKUP = "backup-install-config.yaml"


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


def update_bmh_files(ignition_file, cluster_id, inventory_endpoint):
    if inventory_endpoint:
        hosts_list = utils.get_inventory_hosts(inventory_endpoint, cluster_id)
    else:
        hosts_list = test_utils.get_test_list_hosts(cluster_id)

    with open(ignition_file, "r") as file_obj:
        data = json.load(file_obj)
        storage_files = data['storage']['files']
        # since we don't remove file for now, we don't need to iterate through copy
        for file_data in storage_files:
            if bmh_utils.is_bmh_cr_file(file_data['path']):
                bmh_utils.update_bmh_cr_file(file_data, hosts_list)

    with open(ignition_file, "w") as file_obj:
        json.dump(data, file_obj)


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


def install_config_manipulation(before_installer, config_dir):
    if before_installer:
        shutil.copyfile(os.path.join(config_dir, INSTALL_CONFIG), os.path.join(config_dir,INSTALL_CONFIG_BACKUP))
    else:
        shutil.move(os.path.join(config_dir,INSTALL_CONFIG_BACKUP), os.path.join(config_dir, INSTALL_CONFIG))


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

    if not work_dir:
        raise Exception("working directory was not defined")

    config_dir = os.path.join(work_dir, "installer_dir")
    if install_config:
        subprocess.check_output(["mkdir", "-p", config_dir])
        with open(os.path.join(config_dir, INSTALL_CONFIG), 'w+') as file_obj:
            file_obj.write(install_config)
    if not os.path.isdir(config_dir):
        raise Exception('installer directory is not mounted')

    if not os.path.isfile(os.path.join(config_dir, INSTALL_CONFIG)):
        raise Exception("install config file not located in installer dir")

    install_config_manipulation(config_dir=config_dir, before_installer=True)

    # [TODO] - add extracting openshift-baremetal-install from release image and using it instead of locally compile openshift-intall
    # try:
        # command = "%s/oc adm release extract --command=openshift-baremetal-install  --to=%s \
        # quay.io/openshift-release-dev/ocp-release-nightly@sha256:ba2e09a06c7fca19e162286055c6922135049e6b91f71e2a646738b2d7ab9983" \
        # % (work_dir, work_dir)
    #    subprocess.check_output(command, shell=True, stderr=sys.stdout)
    # except Exception as ex:
    #    raise Exception('Failed to extract installer, exception: {}'.format(ex))

    # command = "OPENSHIFT_INSTALL_INVOKER=\"assisted-installer\" %s/openshift-baremetal-install create ignition-configs --dir %s" \
    #        % (work_dir, config_dir)

    command = "OPENSHIFT_INSTALL_INVOKER=\"assisted-installer\" %s/openshift-install create ignition-configs --dir %s" % (work_dir, config_dir)
    try:
        subprocess.check_output(command, shell=True, stderr=sys.stdout)
    except Exception as ex:
        raise Exception('Failed to generate files, exception: {}'.format(ex))

    install_config_manipulation(config_dir=config_dir, before_installer=True)

    try:
        update_bmh_files("%s/bootstrap.ign" % config_dir, cluster_id, inventory_endpoint)
    except Exception as ex:
        raise Exception('Failed to update BMH CRs in bootstrap ignition, exception: {}'.format(ex))

    if s3_endpoint_url:
        upload_to_s3(s3_endpoint_url, bucket, aws_access_key_id, aws_secret_access_key, config_dir, cluster_id)
    else:
        # for debug purposes
        debug_print_upload_to_s3(config_dir)

if __name__ == "__main__":
    main()
