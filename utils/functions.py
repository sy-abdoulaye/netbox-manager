

from pathlib import Path
import re
import shutil
from os import path as os_path
from os import listdir as os_listdir
from os import makedirs as os_mkdir
from os import remove as os_remove
import sys
from typing import Any, Dict, List, Optional, Type, Tuple, Union
from pydantic import ValidationError
from utils.classes import GetLogger, NetboxManager
from yaml import full_load as yaml_full_load
from yaml import Loader as yaml_loader
from yaml import load as yaml_load
from json import load as load_json
from functools import wraps
import argparse, yaml
import pandas as pd
from yaml import dump as yaml_dump
from json import dump as json_dump
from json import dumps as json_dumps
from difflib import SequenceMatcher
from pyats.datastructures.logic import Or
from genie.harness.main import gTask
from concurrent.futures import ThreadPoolExecutor, as_completed
from re import compile as re_compile
from utils.classes import Trigger_helper
from controller.commands import Command
from os import makedirs, umask

LOGGER = GetLogger.init_log()

def parse_args(dynamic_args=None, parser=argparse.ArgumentParser().parse_known_args, return_kwargs=False):
    if not dynamic_args:
        _, dynamic_args = parser()

    kwargs = {}
    current_key = None

    for arg in dynamic_args:
        if arg.startswith('-'):
            current_key = arg.lstrip('-').replace('-', '_') if return_kwargs else arg
            kwargs[current_key] = []
        else:
            if current_key is None:
                continue
            kwargs[current_key].append(arg)

    # Normalisation des valeurs
    for k, v in kwargs.items():
        if not v:
            kwargs[k] = True
        elif len(v) == 1:
            kwargs[k] = v[0]
        else:
            kwargs[k] = v

    if return_kwargs:
        return kwargs

    return tuple((k, v) for k, v in kwargs.items())


def args_to_cli(kwargs: tuple) -> str:
    """Convert a tuple of arguments to a CLI-compatible string.

    Transforms parsed arguments back into a command-line string format
    suitable for passing to pyATS runtime or subprocess calls.

    Args:
        kwargs (tuple): Tuple of arguments, where each element can be:
            - A tuple of (key, value) where value can be a string or list
            - A single string (flag without value)

    Returns:
        str: Space-separated CLI argument string.

    Example:
        ```python
        args = (
            ('--device', 'router1'),
            ('--interfaces', ['eth0', 'eth1']),
            ('--verbose',)
        )
        cli_string = args_to_cli(args)
        # Returns: " --device router1 --interfaces eth0 eth1 --verbose"
        ```
    """

    cli_args = ''
    for kwarg in kwargs:
        if type(kwarg) is tuple:
            if type(kwarg[1]) is list:
                v_string = ""
                for item in kwarg[1]:
                    v_string = f'{v_string} {item}'
                cli_args = f'{cli_args} {kwarg[0]} {v_string.lstrip()}'
            else:
                cli_args = f'{cli_args} {kwarg[0]} {kwarg[1]}'
        else:
            cli_args = f'{cli_args} {kwarg[0]}'

    return cli_args

def normalize_dashes(data):
    """
    Recursively replace all dashes '-' with underscores '_' in string values.

    This function traverses nested data structures (dicts and lists) and
    replaces dashes in every string it encounters. Non-string values are
    returned unchanged.

    Args:
        data: The input data to normalize. Can be a dict, list, string,
              or any other type.

    Returns:
        The normalized data structure with '-' replaced by '_' in all strings.

    Examples:
        >>> normalize_dashes("Demo-lab")
        'Demo_lab'

        >>> normalize_dashes({"tenant": "Demo-lab", "groups": ["lab-sites"]})
        {'tenant': 'Demo_lab', 'groups': ['lab_sites']}
    """
    if isinstance(data, dict):
        return {k: normalize_dashes(v) for k, v in data.items()}
    if isinstance(data, list):
        return [normalize_dashes(v) for v in data]
    if isinstance(data, str):
        return data.replace("-", "_")
    return data

def find_racktable_file(directory, prefix="racktable"):
    os_mkdir(directory, exist_ok=True)
    for f in os_listdir(directory):
        if f.lower() == prefix.lower() or f.lower().startswith(prefix.lower()):
            return os_path.join(directory, f)
    return None

def remove_files(dir_path, preserve=("raw",)):
    """
    Supprime tous les fichiers et dossiers dans le répertoire donné,
    même si les dossiers ne sont pas vides.
    Préserve les dossiers listés dans `preserve` (ex: 'raw' utilisé
    comme bind mount Docker par Jenkins).
    """
    for name in os_listdir(dir_path):
        path = os_path.join(dir_path, name)
        if os_path.isdir(path) and name not in preserve:
            shutil.rmtree(path)

def update_yaml(
    data: Dict,
    file: Union[str, Path],
    create: bool = False
) -> None:
    """
    Update the content of a YAML file with the provided data.

    Args:
        data: Data to write to the file
        file: Path to the file
        create: If True, create file if it doesn't exist

    Raises:
        FileExistsError: If file exists and create is True
        IOError: If writing to file fails
    """
    mode = 'x' if create else 'w'
    file_path = Path(file)

    try:
        with open(file_path, mode=mode, encoding='utf-8') as f:
            yaml_dump(
                data,
                f,
                indent=4,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True
            )
        LOGGER.debug(f"YAML file updated successfully: {file_path}")
    except FileExistsError:
        LOGGER.error(f"File already exists: {file_path}")
        raise
    except Exception as e:
        LOGGER.error(f"Failed to write YAML file {file_path}: {e}")
        raise


# def deep_merge(
#     source: Dict,
#     destination: Dict,
#     no_list_dups: bool = False
# ) -> None:
#     """
#     Deep merge source dictionary into destination dictionary.

#     Supports merging nested dicts and lists.

#     Args:
#         source: Dictionary to merge from
#         destination: Dictionary to merge into (modified in place)
#         no_list_dups: If True, avoid duplicate items in lists
#     """
#     for key, value in source.items():
#         if not isinstance(destination, dict):
#             continue

#         if isinstance(value, dict):
#             # Recursively merge nested dictionaries
#             destination.setdefault(key, {})
#             deep_merge(value, destination[key], no_list_dups=no_list_dups)

#         elif isinstance(value, list):
#             # Merge lists
#             destination.setdefault(key, [])
#             if no_list_dups:
#                 existing_elements = set(
#                     item for item in destination[key]
#                     if isinstance(item, (str, int, float, bool, type(None)))
#                 )
#                 for item in value:
#                     if item not in existing_elements:
#                         destination[key].append(item)
#                         if isinstance(item, (str, int, float, bool, type(None))):
#                             existing_elements.add(item)
#             else:
#                 destination[key].extend(value)
#         else:
#             # Simple value assignment
#             destination[key] = value


def deep_merge(d: dict, merged: dict, no_list_dups: bool = False):
    """
    Deep merge dictionaries and lists safely.

    Handles:
    - dict merge (recursive)
    - list merge (deduplicate if no_list_dups=True)
    - list of dicts (deduplicate by full dict equality)
    - primitives (overwrite)
    """
    for key, value in d.items():
        target = merged.get(key)

        if isinstance(value, dict):
            # Si target n'est pas un dict, on écrase
            if not isinstance(target, dict):
                merged[key] = {}
                target = merged[key]
            deep_merge(value, target, no_list_dups=no_list_dups)

        elif isinstance(value, list):
            # Si target n'est pas une liste, on la transforme
            if not isinstance(target, list):
                merged[key] = []
                target = merged[key]

            for item in value:
                if no_list_dups:
                    # Deduplication : dict ou primitive
                    if isinstance(item, dict):
                        if not any(item == existing for existing in target):
                            target.append(item)
                    else:
                        if item not in target:
                            target.append(item)
                else:
                    target.append(item)

        else:
            # Valeur primitive → overwrite
            merged[key] = value

def load_testbed_directory(path: str, full_load=True) -> dict:
    """
    Load and merge all YAML files from a testbed directory into a single dict.

    Each YAML file must contain a dictionary compatible with the testbed schema
    (e.g. devices, links, credentials).

    Args:
        path (str): Path to the testbed directory
        full_load (bool): Use yaml.full_load if True

    Returns:
        dict: Merged testbed dictionary
    """
    testbed = {}

    for filename in os_listdir(path):
        if not filename.endswith((".yaml", ".yml")):
            continue

        file_path = os_path.join(path, filename)

        data = load_data_from_file(
            file_extension="yaml",
            file_path=file_path,
            full_load=full_load
        )

        if not isinstance(data, dict):
            raise ValueError(
                f"Invalid testbed data in {filename}: expected dict"
            )

        testbed.update(data)

    return testbed

def load_data_from_file(file_extension: str, file_path: str, data: (list | dict)=None, full_load=True):
    """
    Loads data from a file of a given extension.
    Parameters:
        file_extension (str): The file extension of the file to load
        file_path (str): The file path of the file to load
        data (list | dict): Optional. The list or dictionary to update with the loaded data
    Returns:
        loaded_data (dict): The loaded data from the file.
    """
    # try:
    loaded_data = None
    with open(file_path) as f:
        if file_extension == 'yaml':
            if full_load:
                loaded_data = yaml_full_load(f)
            else:
                loaded_data = yaml_load(
                    f,
                    Loader=yaml_loader
                )
        elif file_extension == 'json':
            loaded_data = load_json(f)
        elif file_extension == 'txt':
            loaded_lines = f.readlines()
            loaded_data = []
            for line in loaded_lines:
                if line:
                    loaded_data.append(line.rstrip())
        elif file_extension == 'css':
            loaded_data = f.read()
        else:
            raise ValueError(f'Unsupported file extension {file_extension}')
    if data:
        data.update(loaded_data)
    else:
        data = loaded_data
    return data

def load_netbox_object_data(key: str, kwargs: dict) -> list:
    """
    Loads NetBox data from the YAML definition.

    :param key: NetBox key (e.g., 'devices', 'interfaces', ...)
    :param kwargs: dictionary containing 'netbox_obj_definition'
    :return: list of loaded data
    """
    netbox_definitions = kwargs.get("netbox_obj_definition")

    if not isinstance(netbox_definitions, dict):
        raise KeyError(
            "'netbox_obj_definition' is missing or is not a dictionary"
        )

    obj_definition = netbox_definitions.get(key)
    if not isinstance(obj_definition, dict):
        raise KeyError(f"NetBox definition not found for key: '{key}'")

    file_path = obj_definition.get("path")
    if not file_path:
        raise ValueError(f"Missing file path for key '{key}'")

    try:
        return load_data_from_file(
            file_extension="yaml",
            file_path=file_path,
            data=[]
        )

    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"NetBox file not found for '{key}': {file_path}"
        ) from exc

    except Exception as exc:
        raise RuntimeError(
            f"Error loading NetBox data for '{key}'"
        ) from exc


def load_testbed(testbed_path: str):
    # Load testbed configuration
    try:
        testbed = load_data_from_file(
            file_path=testbed_path,
            file_extension="yaml"
        )

        LOGGER.info(f"Testbed loaded: {testbed_path}")
        return testbed
    except FileNotFoundError:
        LOGGER.error(f"Testbed file not found: testbeds/{testbed_path}")
        return 1
    except Exception as e:
        LOGGER.error(f"Error loading testbed file: {e}")
        return 1


def validate_devices(
    devices: List[str],
    testbed: Dict[str, Any]
) -> List[str]:
    """
    Validate that selected devices exist in testbed.

    Args:
        devices: List of device names to validate
        testbed: Testbed configuration

    Returns:
        List of valid device names
    """
    valid_devices = []
    invalid_devices = []

    testbed_devices = testbed.devices

    for device in devices:
        if device in testbed_devices:
            valid_devices.append(device)
        else:
            invalid_devices.append(device)

    if invalid_devices:
        LOGGER.warning(
            f"The following devices are not in testbed and will be skipped: "
            f"{', '.join(invalid_devices)}"
        )

    if not valid_devices:
        LOGGER.error("No valid devices found in testbed")
        return []

    LOGGER.info(f"Valid devices: {', '.join(valid_devices)}")
    return valid_devices


def generate_datafiles(datafile_path, devices, actions, actions_devices):
    device_datafile = {}
    triggers = actions_devices.get('triggers')

    triggers_devices_dyns = []
    triggers_devices_statics = []
    if devices:
        for device_name in devices:
            for action_name in actions:
                # if action_name not in triggers:
                    device_datafile.setdefault(device_name, {})
                    device_datafile[device_name][action_name] = {
                        "source": {
                            "class": f"triggers.{action_name}.{action_name.capitalize()}"
                        },
                        "devices": [device_name],
                        "processors": {
                            "pre": {
                                "setup": {
                                    "method": "utils.functions.init_trigger",
                                    "parameters": {
                                        "parallel_triggger": True,
                                    }
                                }
                            },
                            "post": {
                                "cleanup_trigger":{
                                    "method": "utils.functions.cleanup_trigger_processor",
                                }
                            },
                        }
                    }

                    triggers_devices_dyns.append(device_name)

    if triggers:
        for action_name, action_data in triggers.items():
            for device_name in action_data.get('devices'):
                device_datafile.setdefault(device_name, {})
                device_datafile[device_name][action_name] = {
                    "source": {
                        "class": f"triggers.{action_name}.{action_name.capitalize()}"
                    },
                    "devices": [device_name],
                    "processors": {
                        "pre": {
                            "setup": {
                                "method": "utils.functions.init_trigger",
                                "parameters": {
                                    "parallel_triggger": True,
                                }
                            }
                        },
                        "post": {
                            "cleanup_trigger":{
                                "method": "utils.functions.cleanup_trigger_processor",
                            }
                        },
                    }
                }

                triggers_devices_statics.append(device_name)

    for device_name, data_file in device_datafile.items():
        with open(f'{datafile_path}/device_datafiles/{device_name}_datafile.yaml', 'w') as f:
            f.write(yaml_dump(data_file, sort_keys=False))

    return triggers_devices_dyns, triggers_devices_statics

def execute_tasks(kwargs, triggers_devices_statics, triggers_devices_dyn, action_list, lock):
    datafile_path = kwargs['datafile_path']
    devices_async_tasks = {}

    if action_list:
        LOGGER.info("Started tasks execution")
        or_object = Or()
        for action in action_list:
            or_object.expressions.append(re_compile(f'{action}'))

        async_tasks = []
        if triggers_devices_statics:
            for device_name in triggers_devices_statics:
                devices_async_tasks.update({
                    device_name: [
                        gTask(
                            trigger_datafile=f"{datafile_path}/device_datafiles/{device_name}_datafile.yaml",
                            subsection_datafile=f"{datafile_path}/subsection_datafile.yaml",
                            trigger_uids=or_object,
                            taskid=device_name,
                            lock=lock,
                            **kwargs,
                        )
                    ]
                })

        if triggers_devices_dyn:
            for device_name in triggers_devices_dyn:
                devices_async_tasks.update({
                    device_name: [
                        gTask(
                            trigger_datafile=f"{datafile_path}/device_datafiles/{device_name}_datafile.yaml",
                            subsection_datafile=f"{datafile_path}/subsection_datafile.yaml",
                            trigger_uids=or_object,
                            taskid=device_name,
                            lock=lock,
                            **kwargs,
                        )
                    ]
                })

        for _, async_tasks in devices_async_tasks.items():
            for task in async_tasks:
                task.start()

        for _, async_tasks in devices_async_tasks.items():
            for task in async_tasks:
                task.join()

        LOGGER.info("Finished tasks execution")

    return devices_async_tasks

def create_dir(path: Union[str, Path], chmod_: int = 0o0775) -> None:
    """
    Create a directory with specified permissions if it doesn't exist.

    Args:
        path: Path to the directory
        chmod_: Permission mode (default: 0o0775 = rwxrwxr-x)

    Raises:
        OSError: If directory creation fails
    """
    try:
        umask(0)
        makedirs(str(path), mode=chmod_, exist_ok=True)
        LOGGER.debug(f"Directory ensured: {path}")
    except Exception as e:
        LOGGER.error(f"Failed to create directory {path}: {e}")
        raise


from controller.report import Report
def generate_report(section):
    """
    Generate or update report for a device.

    Args:
        device: Device object
        device_name: Name of the device
        kwargs: Additional parameters including facts, action, build info

    Returns:
        None if successful, error code if failed
    """

    if not getattr(section, "report", None):
        # Initialize report
        try:
            path = "./common/data/network"
            section.report = Report(
                trigger_name="network_data",
                path=path,
                lock=section.lock
            )
        except Exception as e:
            LOGGER.error(f"Failed to create report for {section.device.name}: {e}")
            return 4

        section.report.data.setdefault(
            section.device.name,{}
        )
    else:
        # Generate existing report
        try:
            section.report.generate('yaml')
            LOGGER.debug(f"Report generated for device: {section.device.name}")
        except Exception as e:
            LOGGER.error(f"Failed to generate YAML report for {section.device.name}: {e}")


def init_trigger(section):
    section.init_state = "passed"
    for key, value in section.parameters.items():
        setattr(section, key.replace("-", "_"), value)

    section.lock = getattr(section, "lock", None)
    section.device = section.parameters.get('uut')
    section.proxy = section.testbed.devices.get(getattr(getattr(section.device.connections, "vty", None), "proxy", None))
    section.connect = getattr(section, "connect", Trigger_helper.connect)
    section.netbox_obj_definition = section.parameters.get('netbox_obj_definition')
    section.mapping = section.parameters.get('mapping')
    section.cmd = Command()

    section.device.arch = section.device.custom.get('arch')
    section.device.type = section.device.custom.get('type')
    section.device.role = section.device.custom.get('role')
    section.obj_devices_data = section.parameters.get('obj_devices_data')
    section.obj_interfaces_data = section.parameters.get('obj_interfaces_data')

    section.trigger_name = None
    if section and getattr(section, 'uid', {}):
        section.trigger_name, _ = f"{section.uid}".split(".")

    if 'polatis' not in section.device.name:
        try:
            section.connect(device=section.device, proxy=section.proxy)
        except Exception as e:
            LOGGER.error(f"ABORTED: because Failed to connect to device: '{section.device.name}': {e}")
            section.init_state = "aborted"

    generate_report(section)

def cleanup_trigger_processor(section):
    LOGGER.info("generating trigger report...")
    generate_report(section)

    if section.init_state != "passed":
        section.skipped(f"skipping cleanup due to init_state: '{section.init_state}'")

def path_exists(path, is_file=False):
    """ Checks if the given path exists.

    Args:
        path (str): path to check.
        is_file (bool, optional): if path is a file. Defaults to False.

    Returns:
        (bool): True if the path exists, otherwise False.
    """
    if is_file:
        exists = os_path.isfile(path)
    else:
        exists = os_path.exists(path)
    return exists

def save_yaml(data_path, data, merge=False):
    """
    Save or update YAML file(s).

    Args:
        data_path (str): Directory path or full YAML file path.
        data (any): Data to save.
        merge (bool): Merge with existing YAML if file exists.

    Returns:
        bool
    """
    try:
        is_file = data_path.endswith(".yaml")

        if isinstance(data, dict) and not is_file:
            os_mkdir(data_path, exist_ok=True)

            for filename, content in data.items():
                if content is None:
                    continue

                if content.get('path'):
                    file_path = os_path.join(content.get('path'))
                else:
                    file_path = os_path.join(data_path, f"{filename}.yaml")
                _write_yaml_file(file_path, content, merge)
        else:
            dir_path = os_path.dirname(data_path)
            if dir_path:
                os_mkdir(dir_path, exist_ok=True)

            _write_yaml_file(data_path, data, merge)
        return True
    except Exception as e:
        LOGGER.info(f"Error while saving YAML: {e}")
        return False


def _write_yaml_file(file_path, new_data, merge):
    """Write or update a YAML file."""
    if merge and os_path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            existing_data = yaml.safe_load(f) or {}

        if isinstance(existing_data, dict) and isinstance(new_data, dict):
            existing_data.update(new_data)
            new_data = existing_data

    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(
            new_data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

def create_device_module_type(os, model, data: dict, type="module-type", mapping={}):
    MANUFACTURER_BY_OS = {
        "iosxr": "Cisco",
        "iosxe": "Cisco",
        "hvrp": "Huawei",
        "sros": "Nokia",
        "alticeptin": "Altice",
        "isam": "Nokia"
    }

    if type == "module-type":
        # interfaces = data.pop("interfaces", None)
        manufacture = MANUFACTURER_BY_OS.get(os, "Unknown")
        data.update({
            "manufacturer": manufacture,
            "model": model,
            "part_number": model,
            "description": f"{model} providing network forwarding interfaces",
            "weight": 6.88,
            "weight_unit": "kg",
            "comments": (
                f"[{manufacture} Modular Platform Card Data Sheet] "
                "You can view the datasheet online."
            )
        })

        # if interfaces is not None:
        #     data["interfaces"] = interfaces
    else:
        manufacture = MANUFACTURER_BY_OS.get(os, "Unknown")
        if not data.get("manufacturer"):
            data.update({
                "manufacturer": manufacture,
                "model": model,
                "slug": f"{manufacture.casefold()}-{model.casefold()}",
                "part_number": model,
                "u_height": mapping.get(model, 1),
                "is_full_depth": False if model.startswith(("OLT", "ISAM")) else True,
                "airflow": "front-to-rear",
                "weight": 38.2,
                "weight_unit": "kg",
            })


def merge_module_bays(inventory, new_data):
    """
    Add the missing module bays to the inventory.
    """

    existing_bays = inventory.get("module-bays", [])
    new_bays = new_data

    existing_by_name = {bay["name"]: bay for bay in existing_bays}

    for bay in new_bays:
        name = bay.get("name")

        if name not in existing_by_name:
            existing_bays.append(bay)
            existing_by_name[name] = bay

    inventory["module-bays"] = existing_bays

def export_to_json(filename: str, data: dict, results_dir: str = None):
    """
    Exports data to a JSON file in the results directory.
    """

    # Convert results_dir (string or Path) en Path
    results_dir = Path(results_dir) if results_dir else Path("racktables/results")

    # Crée le dossier si nécessaire
    results_dir.mkdir(parents=True, exist_ok=True)

    # Ajoute .json automatiquement si absent
    if not filename.endswith(".json"):
        filename += ".json"

    # Chemin final
    filepath = results_dir / filename

    # Écriture du JSON
    with open(filepath, "w", encoding="utf-8") as f:
        json_dump(data, f, indent=4, ensure_ascii=False)

    return filepath


def extract_label(text: Optional[str]) -> Optional[str]:
    """
    Extracts the device label (e.g., 'ASR-9006') from wiki-style markup.
    Supports both formats:
        - '[[Cisco ASR 9006 | http://...]]'
        - 'Cisco ASR 9006'
    """
    if not text or not isinstance(text, str):
        return None

    # Extract the main text from wiki markup
    match = re.search(r'\[\[\s*([^|\]]+?)\s*(?:\||\]\])', text)
    hw_type = match.group(1).strip() if match else text.strip()
    # Remove "Cisco" (case-insensitive) and extra spaces
    device_type = re.sub(r'(?i)\bcisco\b', '', hw_type).strip()
    # Replace spaces with dashes, remove multiple dashes, and strip edges
    device_type = re.sub(r'\s+', '-', device_type).strip('-')

    return device_type.upper()


def get_device_role_type(device_name: str, hw_type: str, devices_os_supported_roles: dict, expected_netbox_roles) -> tuple[str, str]:
    """
    Determine the operating system (OS) and/or role pattern of a device based on its name.

    The function searches for known device identifiers (roles, models, or substrings)
    inside the given device name using the mapping defined in `devices_os_supported_roles`.

    Example structure of `devices_os_supported_roles`:
        devices_os_supported_roles = {
            "iosxe": ["csr", "cat9k", "asr"],
            "nxos": ["n9k", "n7k", "nexus"],
            "iosxr": ["xr", "asr9k"]
        }

    Args:
        device_name (str): The name of the device (e.g. "lab-csr1000v-1").
        hw_type (str, optional): The hardware type string that may contain placeholders.
        os (bool, optional): If True, only the OS key will be returned.
        device_type (bool, optional): Currently unused, reserved for compatibility.

    Returns:
        str: If `os=True`, returns the detected OS key (e.g. "iosxe") or "unknown".
        tuple[str, str]: If `os=False`, returns a tuple of:
            (matched_pattern, normalized_device_type)
            Example: ("csr", "cat9k")
    """
    if not device_name:
        return "", hw_type

    device_name = device_name.strip()

    # Sanitize hw_type (remove placeholders)
    hw_type = "" if not isinstance(hw_type, str) or pd.isna(hw_type) else hw_type
    hw_type = hw_type.replace("%GPASS%", " ").strip()
    normalized_type = re.sub(r"(?i)\bcisco\b", "", hw_type).replace(" ", "-").upper()

    for _, patterns in devices_os_supported_roles.items():
        for device_role in patterns:
            if str(device_role).upper() in device_name:
                if expected_netbox_roles.get(device_role):
                    device_role = expected_netbox_roles.get(device_role)
                return device_role, normalized_type
    return "", normalized_type


def gather_device_role_type(hw_type: str, role_pattern: str, expected_netbox_roles: dict) -> tuple[str, str]:
    # Normalize hw_type
    type_val = "" if not isinstance(hw_type, str) or pd.isna(hw_type) else hw_type
    type_val = type_val.replace("%GPASS%", " ").strip()

    # Build normalized_type
    normalized_type = (
        re.sub(r"(?i)\bcisco\b", "", type_val)
        .replace(" ", "-")
        .upper()
    )

    # Resolve device_role
    device_role = role_pattern
    if expected_netbox_roles.get(role_pattern):
        device_role = expected_netbox_roles.get(device_role)

    return device_role, normalized_type


def gather_device_os(device_name, devices_os_supported_roles):
    """ Determines the OS type based on the device name.
    """
    for os_name, patterns in devices_os_supported_roles.items():
        if any(str(pattern) in device_name.lower() for pattern in patterns):
            return "generic" if os_name != "iosxr" else os_name
    return 'generic'

def lower_second_char(s):
    if isinstance(s, str) and len(s) >= 2:
        return s[0] + s[1].lower() + s[2:]
    return s

def deep_merge_dict(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            deep_merge_dict(base[key], value)
        else:
            base[key] = value
    return base

def normalize_interface_name(intf, intf_abbrv_mapping_table, os='generic', ignore_case=False):
    """return the full interface name

        Args:
            intf (`str`): Short version of the interface name
            os (`str`): picks what operating system the interface needs to be translated for.
            ignore_case (`bool`): Case in-sensitive matching of names

        Returns:
            Full interface name fit the standard

        Raises:
            None

        example:

            >>> convert_intf_name(intf='Eth2/1')
    """
    if os != "iosxr":
        os = 'generic'

    # takes in the words preceding a digit e.g. the Ge in Ge0/0/1
    m = re.search(r'^([-a-zA-Z]+)', intf)
    # takes in everything after the first encountered digit, e.g. the 0/0/1 in Ge0/0/1
    m1 = re.search(r'(\d[\w.\/-]*)', intf)

    # checks if an interface has both Ge and 0/0/1 in the example of Ge0/0/1
    if hasattr(m, 'group') and hasattr(m1, 'group'):
        # fetches the interface type
        int_type = m.group(0)
        # fetch the interface number
        int_port = m1.group(0)

        try:
            os_type_dict = intf_abbrv_mapping_table[os]
        except KeyError as k:
            print((
                "Check '{}' is in convert dict in utils/common.py, otherwise leave blank.\nMissing key {}\n"
                .format(os, k)))
            return intf

        if ignore_case:
            mapping = {k.lower():v for k,v in os_type_dict.items()}
            name = int_type.lower()
            if name in mapping:
                return mapping[name] + int_port
            else:
                return intf[0].capitalize() + intf[1:].replace(
                    ' ', '').replace('ethernet', 'Ethernet')
        else:
            if int_type in os_type_dict.keys():
                type_ = os_type_dict[int_type]
                if type_:
                    return type_ + int_port
            else:
                return intf[0].capitalize() + intf[1:].replace(
                    ' ', '').replace('ethernet', 'Ethernet')
    else:
        return intf


def find_most_similar_file(search_name, base_dir="./models/devices-types"):
    """
    Searches for the file most similar to the given name in the equipment type directories.

    Args:
        search_name (str): The name to search for (e.g., “7750-SR-7”)
        base_dir (str): The base directory containing the manufacturer subdirectories

    Returns:
        dict: Information about the most similar file found
    """
    base_path = Path(base_dir).expanduser()

    if not base_path.exists():
        return {"error": f"Le répertoire {base_path} n'existe pas"}

    best_match = None
    best_score = 0
    all_matches = []

    # Browse all subdirectorie
    for vendor_dir in base_path.iterdir():
        if not vendor_dir.is_dir() or vendor_dir.name.startswith('.'):
            continue

        # Browse all files in each manufacturer directory
        for file_path in vendor_dir.iterdir():
            if file_path.is_file():
                filename = file_path.stem  # Name without extension

                # Calculate multiple similarity scores
                scores = {
                    'exact': 1.0 if search_name.lower() == filename.lower() else 0.0,
                    'contains': 1.0 if search_name.lower() in filename.lower() else 0.0,
                    'sequence': SequenceMatcher(None, search_name.lower(), filename.lower()).ratio(),
                    'starts_with': 1.0 if filename.lower().startswith(search_name.lower()) else 0.0
                }

                # Weighted overall score
                total_score = (
                    scores['exact'] * 4.0 +
                    scores['starts_with'] * 3.0 +
                    scores['contains'] * 2.0 +
                    scores['sequence'] * 1.0
                ) / 10.0

                match_info = {
                    'path': str(file_path),
                    'vendor': vendor_dir.name,
                    'filename': filename,
                    'full_name': file_path.name,
                    'score': total_score,
                    'scores_detail': scores
                }

                all_matches.append(match_info)

                if total_score > best_score:
                    best_score = total_score
                    best_match = match_info

    # Sort all results by score
    all_matches.sort(key=lambda x: x['score'], reverse=True)

    dict_info = {
        'search_term': search_name,
        'best_match': best_match,
        'top_5_matches': all_matches[:5],
        'total_files_scanned': len(all_matches)
    }

    return dict_info['best_match']


def handle_validation_error(func):
    """Decorator to catch and log Pydantic validation errors."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValidationError as e:
            LOGGER.error(f"Validation error in {func.__name__}: {e}")
            return None
    return wrapper


@handle_validation_error
def validate_data(object_name, data: dict) -> Dict[str, List[Any]]:
    """
    Validate all input data before populating NetBox.

    Args:
        data: Raw data from YAML file

    Returns:
        Dictionary containing validated Pydantic models
        Example: {"sites": [SiteCreate(...), ...], "devices": [...]}
    """
    from schemas import region, tenant, site_group, site, rack, device_role, device_type, \
                        device, interface, ip_address, console_ports, module, inventory_item
    validated_data = {}

    schema_map: Dict[str, Type] = {
        "tenants": tenant.TenantCreate,
        "regions": region.RegionCreate,
        "sites_group": site_group.SiteGroupCreate,
        "sites": site.SiteCreate,
        "racks": rack.RackCreate,
        "device_roles": device_role.DeviceRoleCreate,
        "device_types": device_type.DeviceTypeCreate,
        "devices": device.DeviceCreate,
        "modules": module.ModuleCreate,
        "bundles": interface.InterfaceCreate,
        "interfaces": interface.InterfaceCreate,
        "ip_addresses": ip_address.IPAddressCreate,
        "console_ports": console_ports.ConsolePortCreate,
        "inventory_items": inventory_item.InventoryItemCreate
    }

    # LOGGER.info(json_dumps(data, indent=2))

    def _validate_item(model_class: Type, item: dict, path: str):
        """Helper to validate a single item and log error if any."""
        try:
            return model_class(**item)
        except ValidationError as e:
            LOGGER.error(f"Validation failed for {path}: {e}")
            raise

    # for key, model_class in schema_map.items():
    #     items = data.get(key)
    #     if not items:
    #         continue

    model_class = schema_map.get(object_name)
    validated_items: List[Any] = []

    for device_name, device_data in data.items():
        path_prefix = f"{object_name}[{device_name}]"
        try:
            # Cas 1 : list of objects (e.g., interfaces)
            if isinstance(device_data, list):
                for idx, sub_item in enumerate(device_data):
                    validated_items.append(
                        _validate_item(model_class, sub_item, f"{path_prefix}[{idx}]")
                    )
            # Cas 2 : dictionary with “afi-v4”/“afi-v6”
            elif any(k.startswith("afi-") for k in device_data.keys()):
                for afi, afi_data in device_data.items():
                    if isinstance(afi_data, list):
                        for idx, sub_item in enumerate(afi_data):
                            validated_items.append(
                                _validate_item(model_class, sub_item, f"{path_prefix}[{afi}][{idx}]")
                            )
            # Case 3: Single element
            else:
                validated_items.append(
                    _validate_item(model_class, device_data, path_prefix)
                )

        except ValidationError as e:
            LOGGER.error(f"Validation failed for {object_name}[{device_name}]: {e}")
            raise

    if validated_items:
        validated_data[object_name] = validated_items
        LOGGER.info(f"Validated {len(validated_items)} {object_name}")

    LOGGER.info("✓ Data validation completed successfully")
    return validated_data

# def _process_item(
#     create_func,
#     key: str,
#     data
# ) -> Tuple[bool, str]:
#     """
#     Worker function executed in parallel.
#     """
#     # def display_msg(res_, key, data):
#     #     if res_:
#     #         return True, f"✓ {key[:-1].capitalize()} processed: {data.get('name')}"
#     #     else:
#     #         return False, f"✗ Failed to process {key[:-1]}: {data.get('name')}"

#     # try:
#     print(type(data))
#     if isinstance(data, list):
#         print(key)
#         for payload in data:
#             result = create_func(payload)
#             # display_msg(res_=result, key=key, data=data)
#     else:
#         print(data)
#         result = create_func(data)
#             # display_msg(res_=result, key=key, data=data)
#     # except Exception as e:
#     #     return False, f"✗ Failed to process {key[:-1]} '{data.get('name')}': {e}"

def normalize_items(populated_data):
    """
    Normalize input data into a flat list of dicts.
    Supports:
    - dict
    - dict -> list
    - dict -> dict -> list (afi-v4, afi-v6, etc.)
    """
    items = []

    if isinstance(populated_data, dict):
        for value in populated_data.values():
            if isinstance(value, list):
                items.extend(value)
            else:
                items.append(value)
    elif isinstance(populated_data, list):
        items = populated_data
    else:
        raise TypeError(f"Unsupported data type: {type(populated_data)}")

    return items


def _get_item_name(data: Dict[str, Any]) -> str:
    """Retourne le nom le plus pertinent de l'item."""
    if not isinstance(data, dict):
        return "unknown"
    return data.get("name") or data.get("model") or data.get("device")

def _process_item(create_func, key: str, data: dict) -> Tuple[bool, str]:
    item_type = key[:-1].capitalize()
    name = _get_item_name(data)

    try:
        result = create_func(data)
        if result:
            return True, f"✓ {item_type} processed: {name}"

        return False, f"✗ Failed to process {item_type}: {name}"
    except ValueError as err:
        return True, f"✗ Skipped {item_type}: {name} ({err})"
    except Exception as err:
        return False, f"✗ Failed to process {item_type}: {name} ({err})"

def populate_netbox(
    nb,
    kwargs: dict
) -> bool:
    """
    Populate NetBox using prevalidated data with parallel execution.
    """
    populated_data = Dict[str, List[Any]]
    # Ordered map to ensure dependencies are created first
    action_map = {
        "tenants": nb.create_or_update_tenant,
        "regions": nb.create_or_update_region,
        "sites_group": nb.create_or_update_site_group,
        "sites": nb.create_or_update_site,
        "custom_fields": nb.create_or_update_custom_fields,
        "racks": nb.create_or_update_rack,
        "device_roles": nb.create_or_update_device_role,
        "device_types": nb.create_or_update_device_type,
        "devices": nb.create_or_update_device,
        "modules": nb.create_or_update_module,
        "bundles": nb.create_or_update_interface,
        "interfaces": nb.create_or_update_interface,
        "ip_addresses": nb.create_or_update_ip_address,
        "console_ports": nb.create_or_update_console_port,
        "cables": nb.create_cables_from_interfaces,
        "inventory_items": nb.create_or_update_inventory_item
    }

    objects = normalize_dashes(kwargs.get("objects"))
    if isinstance(objects, str):
        objects = objects.split(" ")

    max_workers = kwargs.get("workers", 8)
    success_count = 0
    error_count = 0

    for key, create_func in action_map.items():
        if objects and key not in objects:
            continue

        try:
            if key !="cables":
                populated_data = load_netbox_object_data(
                    key=key,
                    kwargs=kwargs,
                )
                LOGGER.info(f"{'=' * 60}")
                LOGGER.info(f"Validation of {key} data before integration into Netbox...")
                if not populated_data:
                    LOGGER.warning("No validated data provided — nothing to populate")
                    continue
                validate_data(object_name=key, data=populated_data)
                LOGGER.info(json_dumps(populated_data, indent=2))
        except Exception as e:
            LOGGER.warning(f"Error occured while validating the {key} integrating it into Netbox. Skipped: poupalation to netbox {e}.")
            continue

        if key == "cables":
            populated_data = load_netbox_object_data(
                key="interfaces",
                kwargs=kwargs,
            )

        if key in ["sites", "modules"]:
            max_workers = 1

        items = normalize_items(populated_data)
        LOGGER.info(f"\n{'=' * 60}")
        LOGGER.info(f"Processing {len(items)} {key}...")
        LOGGER.info(f"{'=' * 60}")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_process_item, create_func, key, item)
                for item in items
            ]

            for future in as_completed(futures):
                success, message = future.result()
                if success:
                    success_count += 1
                    LOGGER.info(message)
                else:
                    error_count += 1
                    LOGGER.warning(message)

    nb.close_netbox_session()
    LOGGER.info(f"\n{'=' * 60}")
    LOGGER.info(f"Summary: {success_count} succeeded, {error_count} failed")
    LOGGER.info(f"{'=' * 60}")

    return error_count == 0
