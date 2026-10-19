from typing import Dict, List, Optional
from utils.functions import extract_label, find_most_similar_file, gather_device_os, gather_device_role_type, normalize_interface_name
from .basetransformer import BaseTransformer

class RackTablesTransformer(BaseTransformer):
    def __init__(self, mapping, testbed, site="demo-lab", filter_devices=None):
        super().__init__(mapping, testbed, site, filter_devices=filter_devices)
        self.devices_os_supported_roles = self.mapping.get('devices_os_supported_roles')
        self.expected_netbox_roles = self.mapping.get('expected_netbox_roles')
        self.devices_types_expected = self.mapping.get("devices_types_expected", {})
        self.intf_abbrv_mapping_table = self.mapping.get('interface_abbreviation_mapping_table')
        self.intf_types = self.mapping.get("interfaces_types", {})
        self.zones = self.mapping.get("zones")

    # ============================================================
    #               Pipeline : order of transformations
    # ============================================================
    def pipeline(self):
        return [
            self.transform_devices,
            self.transform_interfaces,
            # self.transform_ip_addresses,
            self.transform_console_ports,
        ]

    def transform_devices(self, row: Dict) -> Optional[Dict]:
        device_name = row.get("name", "").strip()
        hw_type = row.get("HW_type", "")
        role_pattern = row.get("role_pattern", "").strip('-').lower()
        explicit_tags = row.get("explicit_tags", [])
        parent = row.get("role", "")
        zones = self.zones
        tenant = zones.get(explicit_tags[0]) if explicit_tags else ""

        if not role_pattern:
            row.update({
                'fixed': 'The role_pattern field for the equipment is empty, but it is required.'})
            return row

        role, device_type = gather_device_role_type(
            hw_type=hw_type,
            role_pattern=role_pattern,
            expected_netbox_roles=self.expected_netbox_roles
        )

        if not device_type:
            row.update({'fixed': 'The equipment field hw_type is empty after normalization.'})
            return row

        if device_type:
            device_type = extract_label(device_type)
            # device_type_file = find_most_similar_file(device_type)

        device_roles = self.result.setdefault("device_roles", {})
        racks = self.result.setdefault("racks", {})
        devices = self.result.setdefault("devices", {})

        rack_info = row.get('rackspace', {})
        rack_name = rack_info.get('rack_name')
        serial_val = row.get('Numéro_de_série')
        slug = f"{role}-lab"

        racks[rack_name] = {
            "name": rack_name,
            "site": self.site,
            "tenant": tenant,
            "u_height": 47,
            "active": "active"
        }

        # from utils.functions import load_data_from_file
        # device_type_data = load_data_from_file(
        #     file_path=device_type_file['path'],
        #     file_extension="yaml"
        # )
        # device_type = device_type_data.get('model')

        devices_out = {
            device_name: {
                "name": device_name,
                "status": "active",
                "site": self.site,
                "role": slug,
                "device_type": device_type,
                "device_type_path": f"models/device-types/custom/{device_type}.yaml",
                "tenant": tenant,
                "asset_tag": row.get('racktables_id'),
                "rack": rack_name,
                "position": rack_info.get('unit'),
                "face": rack_info.get('atom'),
                "serial": "" if not serial_val else serial_val
            }
        }

        devices.update(devices_out)

    def transform_interfaces(self, row: Dict) -> List[Dict]:
        interfaces_out = {}
        existing_intf = []
        device_name = row.get('name')
        os_name = gather_device_os(
            device_name=device_name,
            devices_os_supported_roles=self.devices_os_supported_roles
        )
        data = row.get('interfaces', [])
        intf_list = []

        for interface in data:
            if_name = normalize_interface_name(
                intf=interface.get("if_name", ""),
                intf_abbrv_mapping_table=self.intf_abbrv_mapping_table,
                os=os_name,
            )
            if not if_name or if_name.lower().startswith("con"):
                continue

            phys = interface.get('physical_port', {})
            virt = interface.get('virtual_port', {})
            label = phys.get('cable', '')
            # if not label:
            #     continue

            prefix = if_name[:2]

            int_type = self.intf_types.get(prefix, "other")
            remote_device = virt.get('remote_device_name', '')
            remote_os = gather_device_os(
                device_name=remote_device,
                devices_os_supported_roles=self.devices_os_supported_roles
            )
            remote_port = normalize_interface_name(
                intf=virt.get('remote_port_name', ''),
                intf_abbrv_mapping_table=self.intf_abbrv_mapping_table,
                os=remote_os
            )

            if if_name not in existing_intf:
                intf_list.append({
                    "name": if_name,
                    "device": device_name,
                    "type": int_type,
                    "label": label if label else "",
                    "description": phys.get("local_port_type_name", ""),
                    "enabled": True,
                    "mark_connected": False,
                    "custom_fields": {
                        "virtual_label": virt.get("cable", ""),
                        "remote_port_name": remote_port,
                        "remote_device": remote_device,
                    }
                })
                existing_intf.append(if_name)

        existing_intf = []
        for afi in ['ipv4', 'ipv6']:
            afi_data = row.get(afi, [])
            if afi_data:

                # Extract virtual interfaces
                intfs_virt = {entry["name"] for entry in afi_data if entry.get("type") == "virtual"}
                for intf in intfs_virt:
                    if intf and intf not in existing_intf:
                        intf_list.append({
                            "name": normalize_interface_name(
                                intf=intf,
                                intf_abbrv_mapping_table=self.intf_abbrv_mapping_table,
                                os=os_name
                            ).strip(),
                            "device": device_name,
                            "type": "virtual"
                        })
                        existing_intf.append(intf)

                # # Extract regular interfaces
                # intfs_reg = {entry["name"] for entry in afi_data if entry.get("type") == "regular"}
                # for intf in intfs_reg:
                #     if intf and intf not in existing_intf:
                #         intf_list.append({
                #             "name": normalize_interface_name(
                #                 intf=intf,
                #                 intf_abbrv_mapping_table=self.intf_abbrv_mapping_table,
                #                 os=os_name
                #             ).strip(),
                #             "device": device_name,
                #             "type": "other"
                #         })
                #         existing_intf.append(intf)

        interfaces_out[device_name] = intf_list
        self.result.setdefault("interfaces", {}).update(interfaces_out)

    def transform_ip_addresses(self, row: Dict) -> None:
        device_name = row["name"]

        explicit_tags = row.get("explicit_tags", [])
        tenant = self.zones.get(explicit_tags[0], "") if explicit_tags else ""

        os_name = gather_device_os(
            device_name=device_name,
            devices_os_supported_roles=self.devices_os_supported_roles
        )

        ip_addresses = []

        for afi in ("ipv4", "ipv6"):
            for iface in row.get(afi, []):
                ip_addr = iface.get("ip")
                if not ip_addr:
                    continue

                interface_name = normalize_interface_name(
                    intf=iface["name"],
                    intf_abbrv_mapping_table=self.intf_abbrv_mapping_table,
                    os=os_name
                ).strip()

                entry = {
                    "address": ip_addr,
                    "device": device_name,
                    "tenant": tenant,
                    "status": "active",
                    "interface": interface_name,
                    "assigned_object_id": interface_name,
                }

                if "Lo" in interface_name:
                    entry["role"] = "loopback"

                ip_addresses.append(entry)

        if ip_addresses:
            self.result.setdefault("ip_addresses", {})[device_name] = ip_addresses

    def transform_console_ports(self, row: Dict) -> List[Dict]:
        device_name = row.get('name')
        intfs = row.get("interfaces", [])

        consoles = [
            interface for interface in intfs
            if interface.get("if_name", "").lower().startswith("con")
        ]

        ports = []
        consoles_out = {}

        for interface in consoles:
            phys = interface.get("physical_port", {})
            virt = interface.get("virtual_port", {})
            label = phys.get("cable", "")
            if not label:
                continue

            ports.append({
                'name': interface['if_name'],
                'device': device_name,
                'type': 'rj-45',
                'label': label,
                'description': phys.get('local_port_type_name', ''),
                'mark_connected': False,
                'custom_fields': {
                    'virtual_label': virt.get('cable', ''),
                    'remote_port_name': virt.get('remote_port_name', ''),
                    'remote_device': virt.get('remote_device_name', '')
                }
            })

        consoles_out[device_name] = ports
        self.result.setdefault("console_ports", {}).update(consoles_out)
