#!/usr/bin/env python

import argparse
import json
import logging
import subprocess
import sys
import os
import boto3
from botocore.exceptions import NoCredentialsError


def get_s3_client(s3_endpoint_url):
    aws_access_key_id = os.environ.get("aws_access_key_id", "accessKey1")
    aws_secret_access_key = os.environ.get("aws_secret_access_key", "verySecretKey1")

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


def remove_bmo_provisioning(ignition_file):
    found = False
    with open(ignition_file, "r") as file_obj:
        data = json.load(file_obj)
        storage_files = data['storage']['files']
        # Iterate through a copy of the list
        for file_data in storage_files[:]:
            if 'baremetal-provisioning-config' in file_data['path']:
                storage_files.remove(file_data)
                found = True
                break
    if found:
        with open(ignition_file, "w") as file_obj:
            json.dump(data, file_obj)


def upload_to_s3(s3_endpoint_url, bucket, install_dir):
    s3_client = get_s3_client(s3_endpoint_url)
    prefix = os.environ.get("CLUSTER_ID")

    for root, _, files in os.walk(install_dir):
        for file_name in files:
            logging.info("Uplading file: %s", file_name)
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


def main():
    parser = argparse.ArgumentParser(description='Generate ignition manifest & kubeconfig')
    parser.add_argument('--s3_endpoint_url', help='s3 endpoint url', default=None)
    parser.add_argument('--s3_bucket', help='s3 bucket', default='test')
    args = parser.parse_args()

    work_dir = os.environ.get("WORK_DIR")
    if not work_dir:
        raise Exception("working directory was not defined")

    install_config = os.environ.get("INSTALLER_CONFIG")
    config_dir = os.path.join(work_dir, "installer_dir")
    if install_config:
        subprocess.check_output(["mkdir", "-p", config_dir])
        with open(os.path.join(config_dir, 'install-config.yaml'), 'w+') as file_obj:
            file_obj.write(install_config)
    if not os.path.isdir(config_dir):
        raise Exception('installer directory is not mounted')

    if not os.path.isfile(os.path.join(config_dir, 'install-config.yaml')):
        raise Exception("install config file not located in installer dir")

    command = "%s/openshift-install create ignition-configs --dir %s" % (work_dir, config_dir)
    try:
        subprocess.check_output(command, shell=True, stderr=sys.stdout)
    except Exception as ex:
        raise Exception('Failed to generate files, exception: {}'.format(ex))

    try:
        remove_bmo_provisioning("%s/bootstrap.ign" % config_dir)
    except Exception as ex:
        raise Exception('Failed to remove BMO prosioning configuration from bootstrap ignition, exception: {}'.format(ex))

    s3_endpoint_url = os.environ.get("S3_ENDPOINT_URL", args.s3_endpoint_url)
    if s3_endpoint_url:
        bucket = os.environ.get('S3_BUCKET', args.s3_bucket)
        upload_to_s3(s3_endpoint_url, bucket, config_dir)
    else:
        # for debug purposes
        debug_print_upload_to_s3(config_dir)

if __name__ == "__main__":
    main()
