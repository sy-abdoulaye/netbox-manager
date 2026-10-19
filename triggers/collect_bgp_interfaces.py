from genie.harness.base import Trigger
from pyats import aetest
from json import dumps as json_dumps
from utils.functions import GetLogger

LOGGER = GetLogger.init_log()


class Collect_bgp_interfaces(Trigger):
    """
    Collecte les voisins BGP sur les équipements réseau et les sauvegarde
    dans common/data/netbox/dcim/bgp_interfaces.yaml.

    Données collectées par voisin BGP :
      - neighbor     : adresse IP du voisin
      - device       : nom du device
      - remote_as    : ASN du voisin
      - state        : état de la session (Established, Idle, Active, ...)
      - vrf          : VRF concernée
      - bgp_instance : instance BGP

    Commandes utilisées (voir common/commands/commands.yaml) :
      - show_bgp_neighbors → show bgp summary (iosxr)
                           → show router bgp summary (sros)
    """

    @aetest.setup
    def setup(self, steps):
        with steps.start("init_state processor") as init_state:
            getattr(init_state, self.init_state)()

    @aetest.test
    def execute_trigger(self, steps):
        with steps.start(f"Collect BGP neighbors on {self.device.name}") as step:
            try:
                cli_command = self.cmd.get_command('show_bgp_neighbors', self.device)
                raw_output = self.device.execute(cli_command)

                # Parsing natif Genie
                try:
                    parsed = self.device.parse(cli_command, output=raw_output)
                except Exception as parse_err:
                    LOGGER.warning(
                        f"Genie parser failed for '{cli_command}' on {self.device.name}: {parse_err}. "
                        f"Storing empty list as fallback."
                    )
                    self.report.data[self.device.name]['bgp_interfaces'] = []
                    step.skipped(f"No parser available for '{cli_command}'")
                    return

                bgp_neighbors = self._extract_bgp_neighbors(parsed)

                LOGGER.info(
                    f"Collected {len(bgp_neighbors)} BGP neighbors on {self.device.name}:\n"
                    + json_dumps(bgp_neighbors, indent=2)
                )
                self.report.data[self.device.name]['bgp_interfaces'] = bgp_neighbors

            except NotImplementedError as e:
                step.aborted(
                    f"Command 'show_bgp_neighbors' not implemented for "
                    f"device {self.device.name} (os={self.device.os}): {e}"
                )
            except Exception as e:
                step.failed(
                    f"Failed to collect BGP neighbors on {self.device.name}: {e}"
                )

    def _extract_bgp_neighbors(self, parsed: dict) -> list:
        """
        Transforme la sortie Genie de 'show bgp summary' en liste normalisée.

        Format Genie attendu (IOS-XR) :
          {
            'instance': {
              '<instance_name>': {
                'vrf': {
                  '<vrf_name>': {
                    'neighbor': {
                      '<neighbor_ip>': {
                        'remote_as': 65000,
                        'bgp_state_pfxrcd': 'Established',
                        ...
                      }
                    }
                  }
                }
              }
            }
          }
        """
        bgp_neighbors = []

        for instance_name, instance_data in parsed.get('instance', {}).items():
            for vrf_name, vrf_data in instance_data.get('vrf', {}).items():
                for neighbor_ip, neighbor_data in vrf_data.get('neighbor', {}).items():
                    state = (
                        neighbor_data.get('bgp_state_pfxrcd')
                        or neighbor_data.get('session_state')
                        or neighbor_data.get('state_pfxrcd')
                    )
                    bgp_neighbors.append({
                        'neighbor': neighbor_ip,
                        'device': self.device.name,
                        'remote_as': neighbor_data.get('remote_as'),
                        'state': state,
                        'vrf': vrf_name,
                        'bgp_instance': instance_name,
                    })

        return bgp_neighbors

    @aetest.cleanup
    def cleanup(self, steps):
        if self.device.is_connected():
            with steps.start(f"Disconnecting from device: {self.device.name}"):
                self.device.disconnect()
