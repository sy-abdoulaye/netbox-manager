'''
pyATS trigger Main Job
The main job for running triggers and generating their report.
'''

from utils.functions import parse_args
from controller.parser import Parser
from json import dump as json_dump
from json import load as load_json
import sys
from copy import deepcopy


def update_json(data: dict, file_name: str, overwrite=True, method="extend", debug=False):
    """
        Update the content of a json file with the sent data.
        If the file doesn't exist, it will be created.
    Args:
        data (dict): The data that will update the content of the file.
        file (str): The name of the file.
        overwrite (bool): If True and the file exists, it will be overwritten.
        method (str): The method to use when updating the json data. Options: 'update' or 'extend'.
    """
    try:
        with open(file=f'{file_name}', mode='x') as file:
            json_dump(data, indent=4, fp=file, sort_keys=False)

    except FileExistsError:
        if not overwrite:
            with open(file=f'{file_name}', mode='r') as file:
                json_data = load_json(file)
            getattr(json_data, method)(deepcopy(data))
            data = json_data

        with open(file=f'{file_name}', mode='w') as file:
            json_dump(data, indent=4, fp=file, sort_keys=False)
    return data

if __name__ == '__main__':
    """
        The following script tests a given parser to be matched with the following inputs:

        How to run:
            python parser_test.py --output-name <output> --device-os <device-os> --command <command-to-be-parsed>

        output is the raw device output must be saved at the following location prior to launching the script:
        ->  ./common/parsers/outputs/<device-os>/<output>

        exemple:
        python check_parser.py --output-name show_platform_x64 --device-os iosxr --command show platform

    """
    #####################################################################################################################
    kwargs = parse_args()

    output_name = ""
    device_os = ""
    command = ""
    for kwarg in kwargs:
        if type(kwarg) is tuple:
            if kwarg[0] == '--output-name':
                output_name = kwarg[1]
            elif kwarg[0] == '--device-os':
                device_os = kwarg[1]
            else:
                command = kwarg[1]

    if not output_name:
        sys.exit("you must use the '--output-name' arg to specify which output to be used")

    if not device_os:
        sys.exit("you must use the '--device-os' arg to specify which device os parser be to used")

    if not command:
        sys.exit("you must use the '--command' arg to specify which command parser be to used")
    #####################################################################################################################
    # show route longer-prefixes {prefix}
    print(f"loading raw output from: './common/parsers/outputs/{device_os}/{output_name}'")
    try:
        with open(f'./common/parsers/outputs/{device_os}/{output_name}') as f:
            output_cli = f.read()
    except FileNotFoundError as e:
        sys.exit(f"{e}")

    print(f"starting parser for command: {command} for device os: {device_os}")
    parser = Parser(
        command,
        output_cli,
        device_os
    )

    print(f"matched with parser: '{parser.name}'")

    print(f"Saving parsed output at: './common/parsers/outputs/{device_os}/{output_name}.json'")
    update_json(
        data=parser.parsed,
        file_name=f"./common/parsers/outputs/{device_os}/{output_name}.json",
    )
    sys.exit(0)
    #####################################################################################################################
