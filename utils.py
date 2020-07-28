import os
import json
from bm_inventory_client import ApiClient, Configuration, api, models



class InventoryHost:

    def __init__(self, host_dict):
        self._host = models.Host(**host_dict)
        self._inventory = models.Inventory(**json.loads(self._host.inventory))


    def get_inventory_host_nics_data(self):
        interfaces_list = [models.Interface(**interface) for interface in self._inventory.interfaces]
        return [{'name': interface.name, 'model': interface.product, 'mac': interface.mac_address, 'ip': self._get_network_interface_ip(interface), 'speed': interface.speed_mbps} for interface in interfaces_list]


    def get_inventory_host_cpu_data(self):
        cpu = models.Cpu(**self._inventory.cpu)
        return {'model': cpu.model_name, 'arch': cpu.architecture, 'flags': cpu.flags, 'clockMegahertz': cpu.frequency, 'count': cpu.count}


    def get_inventory_host_storage_data(self):
        disks_list = [models.Disk(**disk) for disk in self._inventory.disks]
        return [{'name': disk.name, 'vendor': disk.vendor, 'sizeBytes': disk.size_bytes, 'model': disk.model, 'wwn': disk.wwn, 'hctl': disk.hctl, 'serialNumber': disk.serial, 'rotational': True if disk.drive_type == 'HDD' else False} for disk in disks_list] 


    def get_inventory_host_memory(self):
        memory = models.Memory(**self._inventory.memory)
        return int(memory.physical_bytes / 1024 / 1024)


    def get_inventory_host_name(self):
        return self._host.requested_hostname


    def get_inventory_host_system_vendor(self):
        system_vendor = models.SystemVendor(**self._inventory.system_vendor)
        return {'manufacturer': system_vendor.manufacturer, 'productName': system_vendor.product_name, 'serialNumber': system_vendor.serial_number}

    def is_role(self, role):
        return self._host.role == role

    def _get_network_interface_ip(self, interface):
        if len(interface.ipv4_addresses) > 0:
            return interface.ipv4_addresses[0].split("/")[0]
        if len(interface.ipv6_addresses) > 0:
            return interface.ipv6_addresses[0].split("/")[0]
        return " "


def get_inventory_hosts(inventory_endpoint, cluster_id):
    configs = Configuration()
    configs.host = inventory_endpoint
    apiClient = ApiClient(configuration=configs)
    client = api.InstallerApi(api_client=apiClient)
    hosts_list = client.list_hosts(cluster_id=cluster_id)
    return [InventoryHost(host) for host in hosts_list if host['status'] != 'disabled']
