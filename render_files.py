#!/usr/bin/env python

import argparse
import json
import yaml
import logging
import subprocess
import sys
import os
import boto3
import base64
import re
from botocore.exceptions import NoCredentialsError

files_to_remove = ['baremetal-provisioning-config']

bmh_cr_file_pattern = 'openshift-cluster-api_hosts'

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


def contains_files_to_remove(path):
    for file in files_to_remove:
        if file in path:
            return True
    return False


def is_bmh_cr_file(path):
    if bmh_cr_file_pattern in path:
        return True
    return False

def contains_files_to_update(path):
    print ('YEV - check path %s' % path)
    for file in files_to_update:
        if file in path:
            print ('YEV - found file to update')
            return True
    return False


def get_bmh_dict_from_file(file_data):
    source_string = file_data['contents']['source']
    base64_string = re.split("base64,", source_string)[1]
    decoded_string = base64.b64decode(base64_string).decode()
    return yaml.safe_load(decoded_string)


def prepare_annotation_dict(status_dict, hosts_list, is_master):
    inventory_host = find_inventory_host(hosts_list, is_master)
    if inventory_host is None:
        return None

    annot_dict = dict.copy(status_dict)
    nics = [{'name':nic['name'], 'model':"", 'mac' : nic['mac'], 'ip': nic['ipAddr'], 'speedGbps': nic['speed']} for nic in inventory_host['nics']]
    cpu = prepare_cpu_hardware()
    storage = prepare_storage()
    hardware = {'nics': nics, 'cpu': cpu, 'storage': storage}
    annot_dict['hardware'] = hardware
    hosts_list.remove(inventory_host)
    return {'baremetalhost.metal3.io/status': json.dumps(annot_dict)}


def prepare_cpu_hardware():
    flags = []
    return {'arch': "", 'model':"", 'clockMegahertz': 0.0, 'count': 1, 'flags': flags}


def prepare_storage():
    return []


def set_new_bmh_dict_in_file(file_data, bmh_dict):
    decoded_string = yaml.dump(bmh_dict)
    base64_string = base64.b64encode(decoded_string.encode())
    source_string = 'data:text/plain;charset=utf-8;' + 'base64,' + base64_string.decode()
    file_data['contents']['source'] = source_string


def is_master_bmh(bmh_dict):
    if "-master-" in bmh_dict['metadata']['name']:
        return True
    return False


def find_inventory_host(hosts_list, is_master):
    role_to_find = 'master' if is_master else 'worker'
    for host in hosts_list:
        if host['role'] == role_to_find:
            return host
    return None


def update_bmh_cr_file(file_data, hosts_list):
    bmh_dict = get_bmh_dict_from_file(file_data)    
    annot_dict = prepare_annotation_dict(bmh_dict['status'], hosts_list, is_master_bmh(bmh_dict))
    if annot_dict is not None:
        bmh_dict['spec']['bmc']['credentialsName'] = ''
        bmh_dict['metadata']['annotations'] = annot_dict
        set_new_bmh_dict_in_file(file_data, bmh_dict)


def remove_bmo_files(ignition_file, bmh_config_str):
    bmh_config = yaml.safe_load(bmh_config_str)

    hosts_list = bmh_config['hosts']
    with open(ignition_file, "r") as file_obj:
        data = json.load(file_obj)
        storage_files = data['storage']['files']
        # Iterate through a copy of the list
        for file_data in storage_files[:]:
            # if contains_files_to_remove(file_data['path']):
            #    storage_files.remove(file_data)
            if is_bmh_cr_file(file_data['path']):
                update_bmh_cr_file(file_data, hosts_list)

    with open(ignition_file, "w") as file_obj:
        json.dump(data, file_obj)

def upload_to_s3(s3_endpoint_url, bucket, install_dir):
    s3_client = get_s3_client(s3_endpoint_url)
    prefix = os.environ.get("CLUSTER_ID")

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

    try:
        # command = "%s/oc adm release extract --command=openshift-baremetal-install  --to=%s quay.io/openshift-release-dev/ocp-release-nightly@sha256:ba2e09a06c7fca19e162286055c6922135049e6b91f71e2a646738b2d7ab9983" % (work_dir, work_dir)
        command = "%s/oc adm release extract --command=openshift-baremetal-install  --to=%s quay.io/openshift-release-dev/ocp-release-nightly@sha256:b0600325129b5b14d272ad61bcbd7fe609b812ac2620976158046a7bd2c31c62" % (work_dir, work_dir)
        subprocess.check_output(command, shell=True, stderr=sys.stdout)
    except Exception as ex:
        raise Exception('Failed to extract installer, exception: {}'.format(ex))

    command = "OPENSHIFT_INSTALL_INVOKER=\"assisted-installer\" %s/openshift-baremetal-install create ignition-configs --dir %s" % (work_dir, config_dir)
    try:
        subprocess.check_output(command, shell=True, stderr=sys.stdout)
    except Exception as ex:
        raise Exception('Failed to generate files, exception: {}'.format(ex))

    try:
        bmh_config = os.environ.get("BMH_CONFIG")
        # bmh_config = "hosts:\n- role: master\n  hostname: test-bmh1-master-0.redhat.com\n  nics:\n  - name: eth0\n    mac: 52:54:00:4e:ea:7b\n    ipAddr: 192.168.126.10\n    speed: -1\n  - name: eth1\n    mac: 52:54:00:4e:19:64\n    ipAddr: 192.168.140.220\n    speed: -1\n- role: master\n  hostname: test-bmh1-master-1.redhat.com\n  nics:\n  - name: eth0\n    mac: 52:54:00:c2:de:42\n    ipAddr: 192.168.126.11\n    speed: -1\n  - name: eth1\n    mac: 52:54:00:3e:3a:53\n    ipAddr: 192.168.140.120\n    speed: -1\n- role: master\n  hostname: test-bmh1-master-2.redhat.com\n  nics:\n  - name: eth0\n    mac: 52:54:00:2e:c4:dd\n    ipAddr: 192.168.126.12\n    speed: -1\n  - name: eth1\n    mac: 52:54:00:0e:4e:20\n    ipAddr: 192.168.140.204\n    speed: -1\n"
        remove_bmo_files("%s/bootstrap.ign" % config_dir, bmh_config)
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
