from genie.harness.base import Trigger
from pyats import aetest
from json import dumps as json_dumps
from utils.functions import GetLogger

LOGGER = GetLogger.init_log()


class Collecte_isis_interface(Trigger):
    """
    Collecte les interfaces ISIS sur les équipements réseau et les sauvegarde
    dans common/data/netbox/dcim/isis_interfaces.yaml.

    Données collectées par interface ISIS :
      - name        : nom normalisé de l'interface
      - device      : nom du device
      - isis_instance : nom de l'instance ISIS
      - circuit_type : type de circuit (L1, L2, L1L2)
      - state       : état de l'interface (up/down)
      - level_1 / level_2 : détails par niveau si disponibles

    Commandes utilisées (voir common/commands/commands.yaml) :
      - show_isis_interfaces → show isis interface (iosxr)
                             → show router isis interface (sros)
    """

    @aetest.setup
    def setup(self, steps):
        with steps.start("init_state processor") as init_state:
            getattr(init_state, self.init_state)()

    @aetest.test
    def execute_trigger(self, steps):
        with steps.start(f"Collect ISIS interfaces on {self.device.name}") as step:
            try:
                cli_command = self.cmd.get_command('show_isis_interfaces', self.device)
                raw_output = self.device.execute(cli_command)

                # Parsing natif Genie
                try:
                    parsed = self.device.parse(cli_command, output=raw_output)
                except Exception as parse_err:
                    LOGGER.warning(
                        f"Genie parser failed for '{cli_command}' on {self.device.name}: {parse_err}. "
                        f"Storing raw output as fallback."
                    )
                    self.report.data[self.device.name]['isis_interfaces'] = []
                    step.skipped(f"No parser available for '{cli_command}'")
                    return

                isis_interfaces = self._extract_isis_interfaces(parsed)

                LOGGER.info(
                    f"Collected {len(isis_interfaces)} ISIS interfaces on {self.device.name}:\n"
                    + json_dumps(isis_interfaces, indent=2)
                )
                self.report.data[self.device.name]['isis_interfaces'] = isis_interfaces

            except NotImplementedError as e:
                step.aborted(
                    f"Command 'show_isis_interfaces' not implemented for "
                    f"device {self.device.name} (os={self.device.os}): {e}"
                )
            except Exception as e:
                step.failed(
                    f"Failed to collect ISIS interfaces on {self.device.name}: {e}"
                )

    def _extract_isis_interfaces(self, parsed: dict) -> list:
        """
        Transforme la sortie Genie de 'show isis interface' en liste normalisée.

        Format Genie attendu (IOS-XR) :
          {
            'instance': {
              '<instance_name>': {
                'interface': {
                  '<intf_name>': {
                    'circuit_type': 'L1L2',
                    'state': 'isis-intf-state-up',
                    ...
                  }
                }
              }
            }
          }
        """
        isis_interfaces = []

        for instance_name, instance_data in parsed.get('instance', {}).items():
            for intf_name, intf_data in instance_data.get('interface', {}).items():
                entry = {
                    'name': intf_name,
                    'device': self.device.name,
                    'isis_instance': instance_name,
                    'circuit_type': intf_data.get('circuit_type'),
                    'state': intf_data.get('state'),
                }

                # Détails niveau 1
                level_1 = intf_data.get('level_1') or intf_data.get('level-1')
                if level_1:
                    entry['level_1'] = {
                        'adjacency_count': level_1.get('adjacency_count', 0),
                        'metric': level_1.get('metric'),
                    }

                # Détails niveau 2
                level_2 = intf_data.get('level_2') or intf_data.get('level-2')
                if level_2:
                    entry['level_2'] = {
                        'adjacency_count': level_2.get('adjacency_count', 0),
                        'metric': level_2.get('metric'),
                    }

                isis_interfaces.append(entry)

        return isis_interfaces

    @aetest.cleanup
    def cleanup(self, steps):
        if self.device.is_connected():
            with steps.start(f"Disconnecting from device: {self.device.name}"):
                self.device.disconnect()
