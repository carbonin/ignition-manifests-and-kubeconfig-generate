import utils
import yaml


def get_test_list_hosts(cluster_id):
    with open('/data/installer_dir/test_hosts_list.yaml', 'r') as file:
        hosts_list = yaml.full_load(file)
        return [utils.InventoryHost(host) for host in hosts_list if host['status'] != 'disabled']
