import sys
from typing import Any, Callable, Dict, List
from utils.functions import load_data_from_file, find_most_similar_file, merge_module_bays, save_yaml, create_device_module_type
from yaml import dump as yaml_dump
import json

class Network:
    MODULE_TYPES_PATH = "./models/module-types"

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

        try:
            print("Loading network yaml data...")
            self.network_data = load_data_from_file(
                file_path=self.load_data,
                file_extension="yaml"
            )
        except FileNotFoundError as e:
            print(f"File: {self.load_data} not found. {e}")
            return

        for device_name, device_data in self.network_data.items():
            if "polatis" not in device_name:
                self._transform_device(device_name, device_data)

        # print(json.dumps(self.netbox_data['interfaces'], indent=2))

    def _transform_device(self, device_name: str, device_data: dict) -> None:
        for type_, type_data in device_data.items():
            self._dispatch_transform(device_name, type_, type_data)

            obj_data = self.netbox_obj_definition.get(type_)
            if not obj_data:
                print(f"No object definition found for '{type_}' in objects.yaml, skipping save.")
                continue
            data_path = obj_data.get('path')
            if not data_path:
                print(f"No path defined for object {type_}, skipping.")
                continue
            data = self.netbox_data.get(type_)
            if data:
                save_yaml(data_path=data_path, data=data, merge=True)

    def _dispatch_transform(self, device_name: str, type_: str, type_data: Any) -> None:
        handlers: Dict[str, Callable[[str, Any], None]] = {
            "modules": self._handle_modules,
            "bundles": self._handle_bundles,
            "ip_addresses": self._handle_ip_addresses,
            "interfaces": self._handle_interfaces,
            "device_types": self._handle_device_types
        }

        handler = handlers.get(type_)
        if handler:
            handler(device_name, type_data)
        else:
            # Fallback générique : stocke les données directement par device.
            # Utilisé pour les nouvelles actions réseau (isis_interfaces, bgp_interfaces, etc.)
            self.netbox_data.setdefault(type_, {})[device_name] = type_data

    def _handle_modules(self, device_name: str, modules_data: List[dict]) -> None:
        modules_by_device = self.netbox_data.setdefault("modules", {})
        modules_list = modules_by_device.setdefault(device_name, [])

        if not isinstance(modules_list, list):
            modules_by_device[device_name] = modules_list = []

        for module in modules_data:
            module_type_path = find_most_similar_file(
                module.get("module_type"),
                base_dir=self.MODULE_TYPES_PATH
            )
            if module_type_path:
                modules_list.append({
                    "device": device_name,
                    "module_type_path": module_type_path.get("path"),
                    **module
                })

    # def _handle_bundles(self, device_name: str, bundles_data: List[dict]) -> None:
    #     if "interfaces" not in self.netbox_data:
    #         self.netbox_data["interfaces"] = load_data_from_file(
    #             file_path="./common/data/netbox/dcim/interfaces.yaml",
    #             file_extension="yaml"
    #         )

    #     bundles_by_device = self.netbox_data.setdefault("bundles", {})
    #     bundles_list = bundles_by_device.setdefault(device_name, [])

    #     for bundle in bundles_data:
    #         bundle_name = bundle.get("name")
    #         members = bundle.get("members", [])

    #         bundles_list.append({
    #             "name": bundle_name,
    #             "device": device_name,
    #             "type": bundle.get("type"),
    #             "enable": bundle.get("enable")
    #         })
    #         print(id(self.netbox_data["interfaces"][device_name]))
    #         self._attach_bundle_to_interfaces(bundle_name, members, self.netbox_data["interfaces"][device_name])

    # def _handle_ip_addresses(self, device_name: str, ip_addresses_data: Any) -> None:
    #     self.netbox_data.setdefault("ip_addresses", {})[device_name] = ip_addresses_data


    def _handle_bundles(self, device_name: str, bundles_data: List[dict]) -> None:
        # if "interfaces" not in self.netbox_data:
        #     self.netbox_data["interfaces"] = load_data_from_file(
        #         file_path="./common/data/netbox/dcim/interfaces.yaml",
        #         file_extension="yaml"
        #     )

        bundles_by_device = self.netbox_data.setdefault("bundles", {})
        bundles_list = bundles_by_device.setdefault(device_name, [])

        for bundle in bundles_data:
            bundle_name = bundle.get("name")
            # members = bundle.get("members", [])

            bundles_list.append({
                "name": bundle_name,
                "device": device_name,
                "type": bundle.get("type"),
                "enable": bundle.get("enable"),
                **({"custom_fields": bundle["custom_fields"]} if bundle.get("custom_fields") else {})
            })
            # print(id(self.netbox_data["interfaces"][device_name]))
            # self._attach_bundle_to_interfaces(bundle_name, members, self.netbox_data["interfaces"][device_name])

    # def _handle_interfaces(self, device_name: str, interfaces_data: Any) -> None:
    #     self.netbox_data.setdefault("interfaces", {})[device_name] = interfaces_data

    def _handle_ip_addresses(self, device_name: str, ip_addresses_data: Any) -> None:
        self.netbox_data.setdefault("ip_addresses", {})[device_name] = ip_addresses_data

    def _handle_interfaces(self, device_name: str, interfaces_data: Any) -> None:
        for dev_name, device_data in self.network_data.items():
            if "polatis" in dev_name:
                current_device_intf_data =  device_data["interfaces"][device_name]
                interfaces_data = current_device_intf_data

        # bundles_data = self.network_data[device_name]['bundles']
        device_data = self.network_data.get(device_name, {})
        if 'bundles' in device_data:
            bundles_data = device_data.get('bundles', [])
            for bundle in bundles_data:
                members = bundle.get("members", [])
                bundle_name = bundle.get("name")
                self._attach_bundle_to_interfaces(bundle_name, members, interfaces_data)

            self.netbox_data.setdefault("interfaces", {})[device_name] = interfaces_data

    def _handle_device_types(self, _: str, device_type_data: Any) -> None:
        device_type = device_type_data.get('device-type')
        module_bays = device_type_data.get('module-bays')
        os = device_type_data.get('os')
        updated_device_type = self.netbox_data.setdefault("device_types", {}).setdefault(device_type, {})
        create_device_module_type(
            os=os,
            model=device_type,
            data=updated_device_type,
            type="device-type",
            mapping=self.mapping
        )

        if updated_device_type.get('module-bays'):
            merge_module_bays(inventory=updated_device_type, new_data=module_bays)
        else:
            updated_device_type.update({
                'module-bays' : module_bays
            })

    @staticmethod
    def _attach_bundle_to_interfaces(bundle_name, members, interfaces):
        for interface in interfaces:
            for member in members:
                if interface.get("name") == member.get("interface"):
                    interface["lag"] = bundle_name
