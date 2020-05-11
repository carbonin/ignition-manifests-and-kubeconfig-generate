#!/usr/bin/env python

import subprocess
import random
import os
import boto3
from base64 import b64encode
from botocore.exceptions import NoCredentialsError
import logging
import argparse
import sys
import json


def get_s3_client():

        aws_access_key_id = os.environ.get("aws_access_key_id", "accessKey1")
        aws_secret_access_key = os.environ.get("aws_secret_access_key", "verySecretKey1")

        s3 = boto3.client(
            's3',
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            endpoint_url=args.s3_endpoint_url
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


def get_cluster_vip(install_config_path):
    with open(install_config_path, "r") as f:
        data = yaml.load(f)
    return data["platform"]["baremetal"]["apiVIP"]


def add_vip_to_ignition(ignition_file, clusterVIP):
    with open(ignition_file, "r") as f:
        data = json.load(f)
    storageFiles = data['storage'].get('files')
    if storageFiles is None:
        data['storage']['files'] = []
        storageFiles = data['storage']['files']
        
    int_dns = data["ignition"]["config"]["append"][0]["source"].split("//")[1].split(":")[0]
    content = '''{ip}   {name}'''.format(ip=clusterVIP, name=int_dns)
    etc_hosts_info = {
        "filesystem": "root",
        "path": "/etc/hosts",
        "contents": {
          "source": str(b64encode(content.encode('utf-8'))),
          "verification": {}
        },
        "mode": 420
      }
    storageFiles.append(etc_hosts_info)
    with open(ignition_file,"w") as f:
        json.dump(data, f)



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


def upload_files(s3_endpoint_url, bucket, install_dir):
    s3 = get_s3_client()
    prefix = os.environ.get("CLUSTER_ID")
    for root, _, files in os.walk(install_dir):
        for r_file in files:
            logging.info("Uplading file: {}".format(file))
            file = os.path.join(root, r_file)
            s3_file_name = "{}/{}".format(prefix, r_file)
            print(s3_file_name)
            uploaded = upload_to_aws(s3, file, bucket, s3_file_name)


def main():
    parser = argparse.ArgumentParser(description='Generate ignition manifest & kubeconfig')
    parser.add_argument('--file_name', help='output directory name', default="output_dir")
    parser.add_argument('--s3_endpoint_url', help='s3 endpoint url', default=None)
    parser.add_argument('--s3_bucket', help='s3 bucket', default='test')
    parser.add_argument('--dns', help='add /etc/hosts entry for cluster DNS', action='store_true', default=False)

    args = parser.parse_args()
    work_dir = "installer_dir"
    install_config_path = os.path.join(work_dir, 'install-config.yaml')
    
    install_config = os.environ.get("INSTALLER_CONFIG"):
    if install_config:
        subprocess.check_output(["mkdir", "-p", work_dir])
        with open(install_config_path, 'w+') as f:
                f.write(install_config)

    if not os.path.isdir(work_dir):
        raise Exception('installer directory is not mounted')

    if not os.path.isfile(install_config_path):
        raise Exception("install config file not located in {}".format(work_dir))

    if args.dns:
        clusterVip = get_cluster_vip(install_config_path)

    command = "./openshift-install create ignition-configs --dir {}".format(work_dir)
    try:
        subprocess.check_output(command, shell=True, stderr=sys.stdout)
    except Exception as ex:
        raise Exception('Failed to generate files, exception: {}'.format(ex))


    try:
        remove_bmo_provisioning(os.path.join(work_dir, "bootstrap.ign"))
    except Exception as ex:
        raise Exception('Failed to remove BMO prosioning configuration from bootstrap ignition, exception: {}'.format(ex))

    if args.dns:
        for ign in ["master.ign", "worker.ign"]
        add_vip_to_ignition(os.path.join(work_dir, ign), clusterVIP)

    s3_endpoint_url = os.environ.get("S3_ENDPOINT_URL", args.s3_endpoint_url)
    if args.s3_endpoint_url:
        bucket = os.environ.get('S3_BUCKET', args.s3_bucket)
        upload_files(s3_endpoint_url, bucket, args.file_name)

if __name__ == "__main__":
    main()