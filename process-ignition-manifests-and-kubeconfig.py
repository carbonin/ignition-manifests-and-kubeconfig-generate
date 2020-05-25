#!/usr/bin/env python

import subprocess
import random
import os
import boto3
from botocore.exceptions import NoCredentialsError
from base64 import b64decode
import logging
import argparse
import sys
import json


def get_s3_client(s3_endpoint_url):

        aws_access_key_id = os.environ.get("aws_access_key_id", "accessKey1")
        aws_secret_access_key = os.environ.get("aws_secret_access_key", "verySecretKey1")

        s3 = boto3.client(
            's3',
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            endpoint_url=s3_endpoint_url
        )
        return s3


def upload_to_aws(s3, local_file, bucket, s3_file):
    try:
        s3.upload_file(local_file, bucket, s3_file, ExtraArgs={'ACL': 'public-read'})
        print("Upload Successful")
        return True
    except NoCredentialsError:
        print("Credentials not available")
        return False


def remove_bmo_provisioning(ignition_file):
    found = False
    with open(ignition_file, "r") as f:
        data = json.load(f)
        storageFiles = data['storage']['files']
        # Iterate through a copy of the list
        for fileData in storageFiles[:]:
            if 'baremetal-provisioning-config' in fileData['path']:
                storageFiles.remove(fileData)
                found = True
                break
    if found:
        with open(ignition_file,"w") as f:
            json.dump(data, f)


def upload_to_s3(s3_endpoint_url, bucket, install_dir):
    s3 = get_s3_client(s3_endpoint_url)
    prefix = os.environ.get("CLUSTER_ID")

    for root, _, files in os.walk(install_dir):
        for f in files:
            logging.info("Uplading file: {}".format(f))
            file_path = os.path.join(root, f)
            if f == "kubeconfig":
                f = "kubeconfig-noingress"
            s3_file_name = "{}/{}".format(prefix, f)
            print(s3_file_name)
            uploaded = upload_to_aws(s3, file_path, bucket, s3_file_name)


def main():
    parser = argparse.ArgumentParser(description='Generate ignition manifest & kubeconfig')
    parser.add_argument('--s3_endpoint_url', help='s3 endpoint url', default=None)
    parser.add_argument('--s3_bucket', help='s3 bucket', default='test')
    args = parser.parse_args()

    install_config = os.environ.get("INSTALLER_CONFIG")
    work_dir = "installer_dir"
    if install_config:
        subprocess.check_output(["mkdir", "-p", work_dir])
        with open(os.path.join(work_dir, 'install-config.yaml'), 'w+') as f:
                f.write(install_config)

    if not os.path.isdir(work_dir):
        raise Exception('installer directory is not mounted')

    if not os.path.isfile(os.path.join(work_dir, 'install-config.yaml')):
        raise Exception("install config file not located in installer dir")

    command = "./openshift-install create ignition-configs --dir {}".format(work_dir)
    try:
        subprocess.check_output(command, shell=True, stderr=sys.stdout)
    except Exception as ex:
        raise Exception('Failed to generate files, exception: {}'.format(ex))


    try:
        remove_bmo_provisioning("/installer_dir/bootstrap.ign")
    except Exception as ex:
        raise Exception('Failed to remove BMO prosioning configuration from bootstrap ignition, exception: {}'.format(ex))

    s3_endpoint_url = os.environ.get("S3_ENDPOINT_URL", args.s3_endpoint_url)
    if s3_endpoint_url:
        bucket = os.environ.get('S3_BUCKET', args.s3_bucket)
        upload_to_s3(s3_endpoint_url, bucket, work_dir)

if __name__ == "__main__":
    main()
