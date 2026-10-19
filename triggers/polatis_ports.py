import json
import os
from genie.harness.base import Trigger
from utils.functions import GetLogger
from pyats import aetest
from sdk.polatis import Polatis
from pyats.utils.secret_strings import to_plaintext
from json import load as js_load
import copy
import yaml
from utils.functions import normalize_interface_name

LOGGER = GetLogger.init_log()

class Polatis_ports(Trigger):
    def update_interfaces_from_polatis(
        self,
        interfaces: dict[str, list[dict]],
        polatis: dict[str, dict]
    ) -> dict[str, list[dict]]:
        result = copy.deepcopy(interfaces)

        for device, iface_list in result.items():
            for iface in iface_list:
                cf = iface.get("custom_fields", {})
                remote_port = cf.get("remote_port_name")

                if remote_port is not None and str(remote_port) in polatis:
                    polatis_entry = polatis[str(remote_port)]

                    if polatis_entry.get("port_in") == int(remote_port):
                        cf["remote_device"]    = polatis_entry["device_out"]
                        cf["remote_port_name"] = normalize_interface_name(
                            intf=polatis_entry["interface_out"],
                            intf_abbrv_mapping_table=self.mapping['interface_abbreviation_mapping_table'],
                            os=self.testbed.devices[cf["remote_device"]].os
                        )

        return result

    def update_interfaces_yaml(
        self,
        polatis: dict[str, dict],
        filepath: str = "interfaces.yaml"
    ) -> None:
        """
        Lit le fichier interfaces.yaml existant, le met à jour
        avec les données Polatis et l'écrase.

        Args:
            polatis:  dict Polatis (clé = str(port_in))
            filepath: chemin du fichier YAML existant
        """
        with open(filepath, "r", encoding="utf-8") as f:
            interfaces = yaml.safe_load(f)

        updated = self.update_interfaces_from_polatis(interfaces, polatis)

        self.report.data[self.device.name]["interfaces"] = updated

        # with open(filepath, "w", encoding="utf-8") as f:
        #     yaml.dump(
        #         updated,
        #         f,
        #         allow_unicode=True,
        #         default_flow_style=False,
        #         sort_keys=False
        #     )
        # LOGGER.info(f"Fichier mis à jour : {filepath}")

    def save_interfaces_yaml(
        self,
        interfaces: dict[str, list[dict]],
        polatis: dict[str, dict],
        filepath: str = "interfaces.yaml"
    ) -> None:
        """
        Met à jour le dict des interfaces avec les données Polatis
        et écrit le résultat dans le fichier YAML.

        Args:
            interfaces: dict des interfaces par équipement
            polatis:    dict Polatis (clé = str(port_in))
            filepath:   chemin du fichier YAML de sortie
        """
        updated = self.update_interfaces_from_polatis(interfaces, polatis)

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(
                updated,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False
            )
        LOGGER.info(f"Fichier mis à jour : {filepath}")

    def build_polatis_port_mapping(self, data, polatis_device_name):
        """
        Build mapping of Polatis port number -> remote device/interface from RackTables data.

        RT stores port names as zero-padded 3-digit strings ("025"), while the Polatis SDK
        returns integers (25). This function normalizes to string without padding ("25").

        Args:
            racktables_json_path: Path to racktables-data.json (or None to auto-detect)
            polatis_device_name: Polatis device name as it appears in RackTables (e.g. "Polatis-02")

        Returns:
            tuple: (port_mapping dict, file_timestamp string)
                port_mapping: {port_num_str: {device, interface, cable}}
                file_timestamp: modification time of the JSON file
        """

        # Find the Polatis object by name (case-insensitive)
        polatis_obj = None
        for _, obj in data.items():
            if obj.get('name', '').lower() == polatis_device_name.lower():
                polatis_obj = obj
                break

        if not polatis_obj:
            LOGGER.warning(f"Polatis device '{polatis_device_name}' not found in RackTables data")
            return {}

        # Build port mapping from virtual_port links
        # Polatis has ingress ports (1-384) and egress ports (385-768).
        # RT stores only ingress port numbers (001-384) with a label field "ingress.egress"
        # (e.g. "038.422" means ingress 38 is paired with egress 422).
        # We map both ingress and egress port numbers to the same device/interface.
        port_mapping = {}
        for iface in polatis_obj.get('interfaces', []):
            port_name = iface.get('if_name', '')
            try:
                ingress_port = str(int(port_name))  # "038" -> "38"
            except ValueError:
                continue

            vport = iface.get('virtual_port', {})
            if vport and 'remote_device_name' in vport:
                device_info = {
                    'device': vport['remote_device_name'],
                    'interface': vport['remote_port_name'],
                    'cable': vport.get('cable', ''),
                }
                # Map ingress port directly
                port_mapping[ingress_port] = device_info

                # Parse label from physical_port to find paired egress port
                pport = iface.get('physical_port', {})
                label = pport.get('local_port_label', '')
                if '.' in label:
                    try:
                        egress_port = str(int(label.split('.')[1]))
                        port_mapping[egress_port] = device_info
                    except (ValueError, IndexError):
                        pass

        LOGGER.info(f"Loaded RT mapping for {polatis_device_name}: {len(port_mapping)} ports mapped")
        return port_mapping


    @aetest.setup
    def setup(self, steps):
        """Setup phase - Connect to Polatis switch."""
        with steps.start("Initialize trigger") as setup_step:
            with setup_step.start("Connect to Polatis switch") as polatis_step:
                try:
                    # Get credentials and address
                    polatis_creds = self.testbed.credentials.get(
                        self.device.connections.http_session.login_creds[0]
                    )
                    polatis_address = self.device.connections.http_session.host
                    # Connect
                    self.polatis = Polatis(polatis_address, polatis_creds.username)
                    self.polatis.connect(to_plaintext(polatis_creds.password))
                except Exception as e:
                    polatis_step.aborted(
                        f"Aborted: polatis trigger execution because connection failed: {e}"
                    )


    @aetest.test
    def polatis_mapping_ports(self, steps):
        with steps.start("Starting polatis mapping ports") as substep:
            with substep.start("Load racktables raw data") as load_raw_data:
                """Load RackTables port mapping for device/interface enrichment."""
                print(self.ractable_raw_data)
                try:
                    from utils.functions import find_racktable_file
                    raw_data_path = find_racktable_file(
                        directory=self.ractable_raw_data,
                        prefix='racktables-data'
                    )
                    with open(raw_data_path, "r", encoding="utf-8") as f:
                        rack_data = js_load(f)
                except Exception as e:
                    load_raw_data.aborted(f"Can't load RackTables JSON: {e}")

            with substep.start("Process polatis ports mapping") as polatis_mpg:
                self.port_mapping = self.build_polatis_port_mapping(
                    data=rack_data,
                    polatis_device_name=self.device.name
                )
                # LOGGER.info(json.dumps(self.port_mapping, indent=2))

            with substep.start("Get all active cross-connections") as cross_con:
                """Retrieve all active cross-connections and enrich with RT data."""
                try:
                    raw_connections = self.polatis.get_all_connections()
                except Exception as e:
                    cross_con.aborted(f"Aborted: Cannot retrieve connections: {e}")

                # LOGGER.info(raw_connections)

            with substep.start("Building mapping with in/out device and intf") as build_mpg:
                port_mapping = getattr(self, 'port_mapping', {})

                # Build enriched connection dict
                connections = {}
                for conn in raw_connections:
                    port_in = conn[0]
                    port_out = conn[1]
                    in_info = port_mapping.get(str(port_in), {})
                    out_info = port_mapping.get(str(port_out), {})

                    connections[str(port_in)] = {
                        'port_in': port_in,
                        'port_out': port_out,
                        'device_in': in_info.get('device', ''),
                        'interface_in': in_info.get('interface', ''),
                        'cable_in': in_info.get('cable', ''),
                        'device_out': out_info.get('device', ''),
                        'interface_out': out_info.get('interface', ''),
                        'cable_out': out_info.get('cable', ''),
                    }

                LOGGER.info(json.dumps(connections, indent=2))

            with substep.start("Update the interfaces.yaml with polatis") as polatis_step:
                intf_path = self.netbox_obj_definition['interfaces']['path']

                # self.save_interfaces_yaml(interfaces, connections, filepath=intf_path)
                self.update_interfaces_yaml(connections, filepath=intf_path)

    @aetest.cleanup
    def cleanup(self, steps):
        """Cleanup phase - Disconnect from Polatis."""
        with steps.start("Disconnect from Polatis") as step:
            try:
                if hasattr(self, 'polatis'):
                    self.polatis.logout()
                    LOGGER.info("Disconnected from Polatis")
                step.passed("Disconnected from Polatis")
            except Exception as e:
                step.failed(f"Failed to disconnect from Polatis: {e}")
