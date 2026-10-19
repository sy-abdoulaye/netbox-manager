""" curl -X 'GET' 'http://203.0.113.9:9999/api/dcim/interfaces/' \
    -H 'accept: application/json' -H 'Authorization: Token <NETBOX_API_TOKEN>'

NetBox Population Tool

This script populates NetBox with network infrastructure data from YAML files.
It supports creating and updating sites, device roles, device types, devices,
and interfaces with proper validation and error handling.

"""
import sys
from os import makedirs as os_mkdir
from subprocess import run as sub_run
from transformers.network import Network
from utils.classes import NetboxManager, GetLogger, PolatisManager, Transformer
from pyats.topology import loader as topology_loader

from utils.functions import (
    args_to_cli, execute_tasks, generate_datafiles, parse_args, load_data_from_file,
    parse_args, populate_netbox, remove_files, validate_devices
)
from multiprocessing import Lock


LOGGER = GetLogger.init_log()
RAW_DATA_DIR = "common/data/raw"
NETBOX_DATA_DIR = "common/data/netbox"
CONFIG_PATH = "common/config/config.yaml"
MAPPING_DATA_PATH = "common/config/mapping_data.yaml"
NETBOX_OBJECTS_PATH = "common/config/objects.yaml"
NETWORK_DATA_PATH = "common/data/network"
TRIGGERS_DEVICES = "common/config/triggers_devices.yaml"
DIRS = [RAW_DATA_DIR, NETBOX_DATA_DIR, NETWORK_DATA_PATH]
result = {}

def main(runtime):
    """Main entry point for NetBox population script."""
    try:
        kwargs = parse_args(return_kwargs=True)
        kwargs.update({
            "datafile_path": "datafiles",
        })
    except SystemExit:
        return 1

    try:
        LOGGER.info(f"Load mapping data config form {MAPPING_DATA_PATH}...")
        remove_files(dir_path="common/data/")
        kwargs.update({
            "mapping": load_data_from_file(
                file_path=MAPPING_DATA_PATH,
                file_extension="yaml",
            )
        })

        LOGGER.info(f"Load config data yaml file from {CONFIG_PATH} ....")
        kwargs.update({
            "cfg":  load_data_from_file(
                file_path=CONFIG_PATH,
                file_extension="yaml",
            ),
            "tg_devices":  load_data_from_file(
                file_path=TRIGGERS_DEVICES,
                file_extension="yaml",
            ),
        })
        LOGGER.info(f"Load netbox objects path ...")
        kwargs.update({
            "netbox_obj_definition": load_data_from_file(
                file_path=NETBOX_OBJECTS_PATH,
                file_extension="yaml",
            )
        })
        LOGGER.info("Load testbeds to handle devices...")
        kwargs.update({
            "testbed": topology_loader.load('testbeds/full_testbed.yaml')
        })

    except Exception as e:
        LOGGER.error(f"Error loading constants: {e}")
        sys.exit(1)

    lock = Lock()
    raw = kwargs.get('raws_data')
    cfg = kwargs.get('cfg')
    mapping = kwargs.get('mapping')
    netbox_obj_def = kwargs.get('netbox_obj_definition')
    testbed = kwargs.get('testbed')
    network_actions = kwargs.get('network_actions')

    if kwargs.get('supported_platforms'):
        mapping['supported_platforms'] = list(kwargs.get('supported_platforms').split(' '))

    if not raw:
        LOGGER.error("Missing parameter: 'raws_data', you must define it in the command line.")
        return 1

    for directory in DIRS:
        os_mkdir(directory, exist_ok=True)

    try:
        # Extract NetBox connection info
        url = cfg["netbox"]["url"]
        token = cfg["netbox"]["token"]
        LOGGER.info(f"NetBox URL: {url}")
    except KeyError as e:
        LOGGER.error(f"Missing required configuration key: {e}")
        return 1
    except Exception as e:
        LOGGER.error(f"Error loading configuration: {e}")
        return 1

    # Initialize NetBox manager
    try:
        LOGGER.info("Initializing NetBox client...")
        nb = NetboxManager(
            url=url,
            token=token
        )
        if not nb.nb.status():
            raise Exception("Failed to connected to netbox")
        LOGGER.info("Succesfully connected to NetBox")
    except Exception as e:
        LOGGER.error(f"Error initializing NetBox client: {e}")
        return 1

    try:
        Transformer(
            mapping=mapping,
            testbed=testbed,
            ractable_data_path=RAW_DATA_DIR,
            netbox_data_path=NETBOX_DATA_DIR,
            netbox_obj_definition=netbox_obj_def,
            cfg=cfg,
            result=result,
            raw=raw,
            device_roles=kwargs.get('filter_by_device_roles'),
            filter_by_devices=kwargs.get('filter_by_devices'),
        ).transforme(raw)
    except Exception as e:
        LOGGER.error(f"Error while transforming the raw data: {e}")
        return 1

    netbox_devices_data = load_data_from_file(
        file_path=netbox_obj_def['devices']['path'],
        file_extension="yaml"
    )

    netbox_interfaces_data = load_data_from_file(
        file_path=netbox_obj_def['interfaces']['path'],
        file_extension="yaml"
    )
    kwargs.update({
        'obj_devices_data': netbox_devices_data,
        'obj_interfaces_data': netbox_interfaces_data,
        'ractable_raw_data': RAW_DATA_DIR
    })

    network_actions = network_actions.split() if isinstance(network_actions, str) else network_actions
    if network_actions:
        valid_devs = []
        devs = list(netbox_devices_data.keys()) if netbox_devices_data else []
        if devs:
            valid_devs = validate_devices(devs, testbed)

        if not valid_devs:
            LOGGER.error("No valid devices to process. Exiting.")
            return 1

        triggers_devices_dyn, triggers_devices_statics = generate_datafiles(
            datafile_path=kwargs['datafile_path'],
            devices=valid_devs,
            actions=network_actions,
            actions_devices=kwargs['tg_devices']
        )

        execute_tasks(
            kwargs=kwargs,
            triggers_devices_dyn=triggers_devices_dyn,
            triggers_devices_statics=triggers_devices_statics,
            action_list=network_actions,
            lock=lock
        )

        Network(
            netbox_data=netbox_devices_data,
            load_data=f"./{NETWORK_DATA_PATH}/network_data.yaml",
            netbox_obj_definition=netbox_obj_def,
            mapping=mapping['device_type_u_height']
        )


    # ========================================================================
    # POLATIS: Mise à jour des interfaces avec les connexions Polatis
    # ========================================================================

    try:
        LOGGER.info("\\n" + "="*60)
        LOGGER.info("Starting Polatis processing...")
        LOGGER.info("="*60)

        # Configuration Polatis (à adapter selon votre config)
        config_ = kwargs['tg_devices']
        for polatis_name in config_.get('polatis', {}).get('devices'):
            device = testbed.devices[polatis_name]
            polatis_creds = testbed.credentials.get(
                device.connections.http_session.login_creds[0]
            )
            polatis_config = {
                'address': device.connections.http_session.host,
                'username': polatis_creds.username,
                'password': polatis_creds.password,
                'device_name': polatis_name,
                'racktables_path': kwargs['ractable_raw_data'],
                'interface_mapping': mapping.get('interface_abbreviation_mapping_table', {}),
                'testbed': testbed
            }

            # Créer le manager Polatis
            polatis_manager = PolatisManager(
                polatis_address=polatis_config['address'],
                polatis_username=polatis_config['username'],
                polatis_password=polatis_config['password'],
                polatis_device_name=polatis_config['device_name'],
                racktables_data_path=polatis_config['racktables_path'],
                interface_abbreviation_mapping=polatis_config['interface_mapping'],
                testbed=polatis_config.get('testbed')
            )

            # Path vers le fichier interfaces
            interfaces_path = netbox_obj_def['interfaces']['path']

            # Process Polatis et mettre à jour les interfaces
            updated_interfaces = polatis_manager.process(interfaces_path)

            LOGGER.info("="*60)
            LOGGER.info("✓ Polatis processing completed")
            LOGGER.info("="*60 + "\\n")

    except Exception as e:
        LOGGER.error(f"✗ Polatis processing failed: {e}")
        # Décider si c'est critique ou non
        # raise  # Décommentez si vous voulez arrêter l'exécution

    # Populate NetBox
    try:
        if kwargs.get('objects'):
            success = populate_netbox(nb, kwargs)

            if success:
                LOGGER.info("✓ NetBox population completed successfully!")
                return 0
            else:
                LOGGER.warning("✗ NetBox population completed with task failed")
                return 1
    except Exception as e:
        LOGGER.error(f"Fatal error during NetBox population: {e}")
        return 1

if __name__=='__main__':
    """ How to launch  the device deployment script in Netbox
        nohup python main.py --raws-data racktables --network-actions enrich_racktables_data collecte_isis_interface --filter-by-devices N1-5504-PNBIB-1 N1-5504-PNBIB-2 --filter-by-device-roles LEAFBIB --supported_platforms iosxr\
        --objects tenants regions sites racks custom_fields device_roles devices modules bundles interfaces ip_addresses console_ports inventory_items cables > netbox.log 2>&1 &
    """
    kwargs = parse_args()
    cli_args = args_to_cli(kwargs)

    if dict(kwargs).get('--network-actions') or dict(kwargs).get('--raws-data'):
        task = sub_run(
            f"pyats run job {__file__} {cli_args}",
            shell=True,
        )


