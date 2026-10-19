from pathlib import Path
from genie.harness.base import Trigger
from pyats import aetest
from re import fullmatch as re_fullmatch
from re import search as re_search
from re import IGNORECASE as re_ignorecase
from json import dumps as json_dumps
from controller.parser import Parser
from utils.functions import deep_merge_dict, normalize_interface_name, path_exists, save_yaml, create_device_module_type, GetLogger

LOGGER = GetLogger.init_log()
class Enrich_racktables_data(Trigger):

    def add_ifindex_to_interfaces(self, obj_interfaces_data, snmp_dict, interface=True):
        """
        Adds the ifIndex value from the SNMP dictionary to each interface in the list.
        Modifies interfaces_list in place.

        If the interface has a "custom_fields" key, ifIndex is added there.
        Otherwise, ifIndex is added directly to the interface dict.

        Args:
            interfaces_list: list de dict, Each dict represents an interface.
                            Format: [{"name": "...", "device": "...", ...}, ...]
            snmp_dict: dict returned by show_snmp_interface
                    Format: {"interface_name": {"ifIndex": 123}, ...}
        """

        interfaces_list = obj_interfaces_data[self.device.name] if interface else obj_interfaces_data[self.device.name]["bundles"]
        for interface in interfaces_list:
            interface_name = interface.get("name")

            if not interface_name:
                continue

            if interface_name in snmp_dict:
                ifindex_value = snmp_dict[interface_name]["ifIndex"]

                # Check if custom_fields exists
                if "custom_fields" in interface:
                    interface["custom_fields"]["ifIndex"] = ifindex_value
                else:
                    interface["custom_fields"] = {"ifIndex": ifindex_value}

    def add_interfaces_from_ip_data(self, base_dict, new_data):
        """
        Ajoute les interfaces de new_data dans base_dict si elles n'existent pas déjà.

        Args:
            base_dict: dict avec clé "interfaces" contenant la liste des interfaces existantes
                    Format: {"interfaces": [{"name": "...", "type": "...", "status": bool}]}
            new_data: list d'adresses IP avec leurs interfaces associées
                    Format: [{"address": "...", "interface": "...", "status": "active/reserved", ...}]

        Returns:
            dict: base_dict mis à jour avec les nouvelles interfaces
        """
        # Récupérer les noms d'interfaces existantes
        existing_interfaces = {intf["name"] for intf in base_dict.get(self.device.name, [])}

        # Extraire les interfaces uniques de new_data
        new_interfaces = {}
        for entry in new_data:
            interface_name = entry.get("interface", "")

            if not interface_name:
                continue

            # Si l'interface n'existe pas encore dans base_dict et pas déjà traitée
            if interface_name not in existing_interfaces and interface_name not in new_interfaces:
                # Déterminer le type d'interface
                interface_type = self.determine_interface_type(interface_name)

                # Déterminer le status (active = True, reserved = False)
                status = entry.get("status", "reserved") == "active"

                new_interfaces[interface_name] = {
                    "name": interface_name,
                    "device": self.device.name,
                    "type": interface_type,
                    "enable": status
                }

        # Ajouter les nouvelles interfaces à base_dict
        if "interfaces" not in base_dict:
            base_dict["interfaces"] = []

        base_dict[self.device.name].extend(new_interfaces.values())

        return base_dict


    def determine_interface_type(self, interface_name):
        """
        Détermine le type d'interface basé sur son nom.

        Args:
            interface_name: str, nom de l'interface (ex: "1/1/c2/1", "lag-30:999")

        Returns:
            str: type de l'interface
        """

        # LAG interfaces
        if interface_name.startswith("lag-"):
            return "lag"

        # Virtual interfaces (loopback, etc.)
        if any(x in interface_name.lower() for x in ["loopback", "lo", "vport", "nat-", "lns-"]):
            return "virtual"

        # Physical interfaces with channel notation (usually 100G)
        if "/c" in interface_name.lower():
            return "100gbase-x-qsfp28"

        # 10G interfaces (slot 5 typically)
        if interface_name.startswith("5/"):
            return "10gbase-x-sfpp"

        # Default for unknown interfaces
        return "other"

    def merge_two_module_dicts(self, base_dict, new_dict):
        """
        Merge the new_dict into base_dict by extending lists for each key.
        Only merges existing keys or adds new keys if they don't exist.
        """
        for key, items in new_dict.items():
            if key in base_dict:
                base_dict[key].extend(items)
            else:
                base_dict[key] = items.copy()
        return base_dict

    def add_device_name(self, parsed_data: list, device_name: str) -> list:
        """
        Adds the 'device' key to each IP address entry.

        Args:
            parsed_data (list): list of parsed IP address dictionaries.
            device_name (str): device name.

        Returns:
            list: enriched list
        """
        for entry in parsed_data:
            entry["device"] = device_name
        return parsed_data

    def extract_interface_id(self, interface):
        """
        Returns a vendor-agnostic canonical interface identifier.

        Matching rules (priority order):
        1. Pure numeric paths (e.g. 1/1/1, 0/3/38, 0/1/0/26)
        2. Interfaces ending with a numeric path (Cisco / Huawei)
        3. Logical interfaces (Eth-Trunk, Port-channel, lag, Loopback, Vlan, etc.)
        4. Fallback: return the original interface name
        """

        if not interface:
            return interface

        interface = interface.strip()

        # Pure numeric interface (Nokia SR OS style)
        if re_fullmatch(r'\d+(?:/\d+)+', interface):
            return interface

        # Cisco / Huawei physical interfaces
        m = re_search(r'(\d+(?:/\d+)+)$', interface)
        if m:
            return m.group(1)

        # Logical / aggregated interfaces
        logical_patterns = (
            r'(Eth-Trunk\d+)',
            r'(Port-Channel\d+)',
            r'(port-channel\d+)',
            r'(lag-\d+)',
            r'(Lag\d+)',
            r'(Bundle-Ether\d+)',
            r'(ae\d+)',           # Juniper
            r'(Vlan\d+)',
            r'(Loopback\d+)',
            r'(LoopBack\d+)',
            r'(Null0)',
            r'(NULL0)'
        )

        for pattern in logical_patterns:
            m = re_search(pattern, interface, re_ignorecase)
            if m:
                return m.group(1)

        # Fallback
        return interface

    def sync_interfaces(self, module_type_parsed, obj_interfaces_data, device):
        """
        Update existing interfaces or add missing ones for a given device.
        Interface matching is done using a canonical interface_id,
        while preserving the most explicit interface name when available.
        """

        interfaces_existantes = obj_interfaces_data.setdefault(device, [])
        # Build index: interface_id -> interface object
        intf_by_id = {
            self.extract_interface_id(iface["name"]): iface
            for iface in interfaces_existantes
        }

        for iface in module_type_parsed.get("interfaces", []):

            raw_name = iface.get("name")
            iface_type = iface.get("type")
            status = iface.get('status')

            if not raw_name or not iface_type:
                continue

            # Normalize name (vendor / OS specific)
            name = normalize_interface_name(
                intf=raw_name,
                intf_abbrv_mapping_table=self.mapping['interface_abbreviation_mapping_table'],
                os=self.device.os
            )

            intf_id = self.extract_interface_id(name)

            # Interface already exists → UPDATE
            if intf_id in intf_by_id:
                existing_iface = intf_by_id[intf_id]
                existing_iface["enabled"] = status

                # Update type if needed
                if existing_iface.get("type") != iface_type:
                    existing_iface["type"] = iface_type

                # Prefer the most explicit name
                if len(name) > len(existing_iface.get("name", "")):
                    existing_iface["name"] = name

                # updated_interface.append(existing_iface)

            # Interface does not exist → CREATE
            else:
                if self.device.os == "sros":
                    new_iface = {
                        "name": name,
                        "device": device,
                        "type": iface_type,
                        "enable": True
                    }

                    interfaces_existantes.append(new_iface)
                    # intf_by_id[intf_id] = new_iface
                    interfaces_existantes.append(new_iface)

    def add_interface(self, base, new_data, device):
        interfaces_existantes = base.setdefault(device, [])

        intf_by_id = {
            self.extract_interface_id(iface["name"]): iface
            for iface in interfaces_existantes
        }


    @aetest.setup
    def setup(self, steps):
        with steps.start("init_state processor") as init_state:
            getattr(init_state, self.init_state)()

    @aetest.test
    def execute_trigger(self, steps):
        with steps.start("Get device modules and cards") as step:
            try:
                cli_command = self.cmd.get_command('show_router_cards', self.device)

                if isinstance(cli_command, str):
                    cmd_output_parsed = Parser(
                        cli_command,
                        self.device.execute(cli_command),
                        self.device.os
                    ).parsed
                    LOGGER.info(json_dumps(cmd_output_parsed, indent=2))
                    self.module_data_parsed = cmd_output_parsed
                else:
                    for cmd in cli_command:
                        cmd_output_parsed = Parser(
                            cmd,
                            self.device.execute(cmd),
                            self.device.os
                        ).parsed

                        if self.device.os != "sros":
                            if isinstance(cmd_output_parsed, dict):
                                self.module_data_parsed = cmd_output_parsed
                            else:
                                # Create a dictionary for quick access by module_bay
                                cmd_output_dict = {item['module_bay']: item['module_type'] for item in cmd_output_parsed}

                                # Browse module_data_parsed categories
                                for _, modules in self.module_data_parsed.items():
                                    for module in modules:
                                        bay = module['module_bay']
                                        # If module_bay exists in cmd_output, update module_type
                                        if bay in cmd_output_dict:
                                            module['module_type'] = cmd_output_dict[bay]
                        else:
                            if hasattr(self, "module_data_parsed"):
                                self.merge_two_module_dicts(self.module_data_parsed, cmd_output_parsed)
                            else:
                                self.module_data_parsed = cmd_output_parsed
            except NotImplementedError as e:
                aborted_msg = f"ABORTED because an error occurred while getting command via abstract command: 'show_router_cards'.Full trace:{e}"
                step.aborted(aborted_msg)

        if self.device.os != "isam":
            with steps.start("Get device bundle with members") as step:
                try:
                    cli_command = self.cmd.get_command('show_router_bundle', self.device)
                    bundle_output_parsed = Parser(
                        cli_command,
                        self.device.execute(cli_command),
                        self.device.os
                    ).parsed

                    for bundle in bundle_output_parsed:
                        # Standardization of member interfaces and bunlde
                        bundle['name'] = normalize_interface_name(
                            intf=bundle.get('name'),
                            intf_abbrv_mapping_table=self.mapping['interface_abbreviation_mapping_table'],
                            os=self.device.os
                        )

                        for member in bundle.get('members', []):
                            member['interface'] = normalize_interface_name(
                                intf=member.get('interface'),
                                intf_abbrv_mapping_table=self.mapping['interface_abbreviation_mapping_table'],
                                os=self.device.os
                            )
                    self.report.data[self.device.name]["bundles"] = bundle_output_parsed
                except NotImplementedError as notIm_error:
                    step.aborted(f"Command not implemented for device {self.device}: {notIm_error}")
                except Exception as e:
                    aborted_msg = f"ABORTED because an error occured while getting command via abstract command: 'show_router_bundle'. Full trace:{e}"
                    step.aborted(aborted_msg)

        with steps.start(f"Get {self.device.name} interfaces ..."):
            module_type_parsed = {}
            cli_cmd_location = self.cmd.get_command("show_router_interfaces", self.device)
            if self.device.os == "alticeptin":
                for slot in self.module_data_parsed.get('LC'):
                    if slot.get('module_type').startswith(('UL', 'TU')):
                        cli_command = cli_cmd_location.format(slot=slot['node'])
                        parsed = Parser(
                            cli_command,
                            self.device.execute(cli_command),
                            self.device.os
                        ).parsed

                        deep_merge_dict(module_type_parsed, parsed)
            else:
                module_type_parsed = Parser(
                    cli_cmd_location,
                    self.device.execute(cli_cmd_location),
                    self.device.os
                ).parsed

                LOGGER.info(json_dumps(module_type_parsed, indent=2))
                # self.updated_interfaces = []
                self.sync_interfaces(
                    module_type_parsed=module_type_parsed,
                    obj_interfaces_data=self.obj_interfaces_data,
                    # updated_interface=self.updated_interfaces,
                    device=self.device.name
                )

        if self.device.os == "iosxr":
            with steps.start("Get each interface IfIndex") as step:
                cli_command = self.cmd.get_command("show_router_interface_index", self.device)
                snmp_dict_parsed = Parser(
                    cli_command,
                    self.device.execute(cli_command),
                    self.device.os
                ).parsed

                self.add_ifindex_to_interfaces(
                    obj_interfaces_data=self.obj_interfaces_data,
                    snmp_dict=snmp_dict_parsed,
                    interface=True
                )

                self.add_ifindex_to_interfaces(
                    obj_interfaces_data=self.report.data,
                    snmp_dict=snmp_dict_parsed,
                    interface=False
                )

        if self.device.os not in ["alticeptin", "isam"]:
            with steps.start("Get interfaces ip addresses") as step:
                if self.device.os != "sros":
                    try:
                        self.data_ip_addresses = []
                        # IPv4
                        cli_command_v4 = self.cmd.get_command("show_router_interface_ipv4_address", self.device)
                        v4_parsed = Parser(
                            cli_command_v4,
                            self.device.execute(cli_command_v4),
                            self.device.os
                        ).parsed

                        self.data_ip_addresses.extend(self.add_device_name(v4_parsed, self.device.name))

                        # IPv6
                        cli_command_v6 = self.cmd.get_command("show_router_interface_ipv6_address", self.device)
                        v6_parsed = Parser(
                            cli_command_v6,
                            self.device.execute(cli_command_v6),
                            self.device.os
                        ).parsed

                        self.data_ip_addresses.extend(self.add_device_name(v6_parsed, self.device.name))
                    except NotImplementedError as notIm_error:
                        step.aborted(
                            f"Command not implemented for device {self.device}: {notIm_error}"
                        )
                    except Exception as e:
                        step.aborted(
                            f"ABORTED because an error occurred while getting IP addresses: {e}"
                        )
                else:
                    self.data_ip_addresses = []
                    # IPv4
                    cli_command = self.cmd.get_command("show_router_interface_address", self.device)
                    output_parsed = Parser(
                        cli_command,
                        self.device.execute(cli_command),
                        self.device.os
                    ).parsed

                    self.data_ip_addresses.extend(self.add_device_name(output_parsed, self.device.name))
                    self.add_interfaces_from_ip_data(self.obj_interfaces_data, self.data_ip_addresses)

        base_path_module_type = self.netbox_obj_definition['module_types']['path']
        base_path_device_type = self.netbox_obj_definition['device_types']['path']
        device_type_data = {}
        updated_modules = []

        def extract_digit(module_bay):
            m = re_search(r'(\d+)(?:$|$)', module_bay)
            if m:
                return m.group(1)
            if module_bay.startswith("A"):
                return 1
            else:
                return 2

        for _, module_data in self.module_data_parsed.items():
            for module in module_data:
                node = module['node']
                module_type = module['module_type']
                module_bay = module['module_bay']

                # if key in self.mapping['supported_linecards_rp']:
                data_path = f"{base_path_module_type}/{module_type}.yaml"
                is_ok = path_exists(path=data_path, is_file=True)
                if not is_ok:
                    with steps.start(f"Create module-type file: {module_type}"):
                        data = {}
                        create_device_module_type(os=self.device.os, model=module_type, data=data)
                        save_yaml(
                            data_path=data_path,
                            data=data,
                        )

                updated_modules.append(module)

                if self.device.os != "sros":
                    device_type_data.setdefault("module-bays", []).append(
                        {
                            "name": node,
                            "label": module_bay,
                            "position": int(extract_digit(module_bay))
                        }
                    )
                else:
                    device_type_data.setdefault("module-bays", []).append(
                        {
                            "name": module_bay,
                            "label": module_bay,
                            "position": int(extract_digit(module_bay))
                        }
                    )

        LOGGER.info(json_dumps(device_type_data, indent=2))
        device_type = self.obj_devices_data[self.device.name].get('device_type')

        self.report.data[self.device.name].update({
            'modules': updated_modules,
            'interfaces': self.obj_interfaces_data[self.device.name],
            'device_types': {
                'module-bays': device_type_data['module-bays'],
                'device-type': device_type,
                'os': self.device.os
            },
            'inventory_items': []
        })

        if self.device.os not in ["alticeptin", "isam"]:
            with steps.start("Clean up collected IP address data"):
                def clean_ip_addresses(data_ip_address: dict, data_interfaces: dict) -> dict:
                    """
                    Removes IPs whose interface does not exist in data_interfaces.
                    Returns a new, cleaned dictionary..
                    """

                    cleaned_data = []

                    for ip_list in data_ip_address:
                        interface_names = {iface["name"] for iface in data_interfaces}
                        intf_by_address = ip_list.get("interface")
                        if intf_by_address in interface_names or "Bundle" in intf_by_address:
                            cleaned_data.append(ip_list)

                    return cleaned_data

                LOGGER.info("Removes IPs whose interface does not exist racktables data")
                cleaned_data = clean_ip_addresses(
                    data_ip_address=self.data_ip_addresses,
                    data_interfaces=self.report.data[self.device.name]["interfaces"]
                )

                self.report.data[self.device.name]["ip_addresses"] = cleaned_data

        if self.device.os == "iosxr":
            with steps.start("Update interface by adding module"):
                for module in updated_modules:
                    node = module['node']
                    module_bay = module['module_bay']
                    if not module_bay.startswith(tuple(self.mapping['supported_linecards_rp'])):
                        continue

                    cli_command = self.cmd.get_command("show_router_interface_location", self.device).format(location=node)

                    location_interfaces_parsed = Parser(
                        cli_command,
                        self.device.execute(cli_command),
                        self.device.os
                    ).parsed

                    normalized_new = {}

                    for name, data in location_interfaces_parsed["interfaces"].items():
                        norm_name = normalize_interface_name(
                            intf=name,
                            intf_abbrv_mapping_table=self.mapping['interface_abbreviation_mapping_table'],
                            os=self.device.os
                        )
                        normalized_new[norm_name] = data

                    for intf in self.report.data[self.device.name]["interfaces"]:
                        name = intf["name"]
                        if name in normalized_new:
                            intf['module'] = node

        if self.device.os in ["iosxr", "iosxe"]:
            with steps.start("Update interfaces and modules with inventory data") as step:
                try:
                    cli_command = self.cmd.get_command('show_router_inventory', self.device)
                    if self.device.os == "iosxr":
                        inventory = self.device.parse(cli_command)
                    elif self.device.os == "iosxe":
                        inventory = Parser(
                            cli_command,
                            self.device.execute(cli_command),
                            self.device.os
                        ).parsed

                    modules_data = self.report.data.get(self.device.name, {}).get("modules", [])
                    interfaces_data = self.report.data.get(self.device.name, {}).get("interfaces", [])
                    inventory_items = self.report.data.get(self.device.name, {}).get("inventory_items", [])

                    inventory_modules = inventory.get('module_name', {})

                    # 🔹 Index pour lookup rapide (O(1) au lieu de O(n²))
                    inventory_index = {
                        key: {
                            "serial": val.get("sn", ""),
                            "description": val.get("descr", ""),
                            "pid": val.get("pid", ""),
                            "vid": val.get("vid", "")
                        }
                        for key, val in inventory_modules.items()
                    }

                    # 🔹 Fonction de matching (plus robuste)
                    def match_inventory(target, inventory_keys, contains=True):
                        if not target:
                            return None
                        for key in inventory_keys:
                            if not contains:
                                if key == target:
                                    return key
                            else:
                                if key in target or target in key:
                                    return key
                        return None

                    # 🔹 Enrich modules
                    for module in modules_data:
                        node = module.get('node', '')
                        module_bay = module.get('module_bay', '')

                        match_key = (
                            match_inventory(node, inventory_index.keys()) or
                            match_inventory(module_bay, inventory_index.keys())
                        )

                        if match_key:
                            module.update(inventory_index[match_key])

                    # 🔹 Enrich interfaces
                    for iface in interfaces_data:
                        name = iface.get('name', '')

                        match_key = match_inventory(name, inventory_index.keys(), contains=False)

                        if match_key:
                            iface.update({
                                "description": inventory_index[match_key]["description"]
                            })

                            inventory_items.append({
                                'device': self.device.name,
                                'name': name,
                                'serial': inventory_index[match_key]["serial"],
                                'label': inventory_index[match_key].get("vid", ""),
                                'part_id': inventory_index[match_key].get("pid", ""),
                                'description': inventory_index[match_key]["description"],
                                'manufacturer': self.device.custom.get("manufacturer", ""),
                                'component_type': 'dcim.interface',
                                'component_id': name
                            })

                    # 🔹 Enrich device data
                    match_key = match_inventory("Rack", inventory_index.keys())
                    if match_key:
                        self.report.data[self.device.name]['devices'] = self.obj_devices_data.get(self.device.name, {})
                        self.report.data[self.device.name]['devices'].update({
                            "serial": inventory_index[match_key]["serial"],
                            "description": inventory_index[match_key]["description"],
                        })
                except Exception as e:
                    step.failed(
                        f"Failed to enrich inventory data for device {self.device.name}: {str(e)}"
                    )

    @aetest.cleanup
    def cleanup(self, steps):
        if self.device.is_connected():
            with steps.start(f"Disconnecting to device: {self.device.name}"):
                self.device.disconnect()