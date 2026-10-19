

class Command:
    """
        Matches the command to the device os and architecture.
        If the command is not found, it raises NotImplementedError.
    """
    def __init__(self):
        self.load_commands()

    def load_commands(self):
        # Deferred Imports to avoid circular imports
        from utils.functions import load_data_from_file
        from pyats.datastructures import NestedAttrDict

        self.commands =  NestedAttrDict(
            load_data_from_file(
                file_path="./common/commands/commands.yaml",
                file_extension="yaml",
            )
        )

    def get_command(self, cmd_name, device):
        # raise an exception if the command is not supported
        if cmd_name not in self.commands:
            raise NotImplementedError(f"abstract command: {cmd_name} is not supported.")

        # Check if the device os is supported for the command.
        if device.os not in self.commands[cmd_name].keys():
            raise NotImplementedError(f"abstract command: {cmd_name} is not supported for platform: {device.os}.")

        # Check if the device architecture is supported for the command.
        if type(self.commands[cmd_name][device.os]) is str or \
            type(self.commands[cmd_name][device.os]) is list:
            command = self.commands[cmd_name][device.os]
        else:
            if device.arch:
                if device.arch not in self.commands[cmd_name][device.os].keys():
                    raise NotImplementedError(f"abstract command: {cmd_name} is not supported for platform: {device.os} with architecture: {device.arch}")

            command = self.commands[cmd_name][device.os][device.arch]
        return command
