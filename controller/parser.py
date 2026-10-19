"""Parser module for matching commands to device-specific parsers."""
import importlib
import os
import re
from typing import Dict, Tuple, Optional, Any
from json import dumps as json_dumps
from pathlib import Path
from utils.classes import GetLogger

LOGGER = GetLogger.init_log()


class Parser:
    """
    Matches commands to device OS and architecture-specific parsers.

    The parser dynamically loads platform-specific parsing modules and
    matches commands to appropriate parser functions based on docstring patterns.
    """

    # Attributes to skip when importing parser modules
    SKIP_ATTRS = {
        '__builtins__', '__cached__', '__doc__', '__file__',
        '__loader__', '__name__', '__package__', '__spec__',
        'logging', 're', 'ttp', 'os', 'json',
    }

    # Parameters that should match non-whitespace only (stricter matching)
    STRICT_PARAMS = {'vrf', 'rd', 'instance', 'vrf_type', 'feature'}

    def __init__(self, command: str, raw_output: str, device_os: str):
        """
        Initialize the parser and find matching parser for the command.

        Args:
            command: CLI command to parse
            raw_output: Raw output from the command
            device_os: Device operating system (e.g., 'cisco_xr', 'cisco_xe')

        Raises:
            NotImplementedError: If platform or command parser not found
            Exception: If parser module has configuration issues
        """
        self.command = command
        self.device_os = device_os
        self.raw_output = raw_output
        self.platforms = []
        self.parsers = []
        self.name = None
        self.package = None
        self.parsed = None

        # Discover and validate platform
        self._discover_platforms()
        self._validate_platform()

        # Load and match parser
        self._load_parser()

    def _discover_platforms(self) -> None:
        """Discover available platform directories."""
        parsers_path = Path('./common/parsers/platforms')

        if not parsers_path.exists():
            raise NotImplementedError(
                f"Parsers directory not found: {parsers_path}"
            )

        self.platforms = [
            d.name for d in parsers_path.iterdir()
            if d.is_dir() and not d.name.startswith('__')
        ]
        LOGGER.debug(f"Available platforms: {self.platforms}")

    def _validate_platform(self) -> None:
        """Validate that the device OS platform is supported."""
        if self.device_os not in self.platforms:
            raise NotImplementedError(
                f"Platform '{self.device_os}' is not supported. "
                f"Available platforms: {', '.join(self.platforms)}"
            )
        LOGGER.debug(f"Platform validated: {self.device_os}")

    def _load_parser(self) -> None:
        """Load parser modules and find matching parser for the command."""
        parsers_path = Path(f'./common/parsers/platforms/{self.device_os}')

        # Get all parser module files
        parser_files = [
            f.stem for f in parsers_path.iterdir()
            if f.is_file() and f.suffix == '.py' and not f.name.startswith('__')
        ]

        if not parser_files:
            raise NotImplementedError(
                f"No parser modules found for platform: {self.device_os}"
            )

        LOGGER.debug(f"Found parser modules: {parser_files}")

        # Try each parser module until we find a match
        for parser_name in parser_files:
            parser_locals = self._import_parser_module(parser_name)

            try:
                match_result = self.match(self.command, parser_locals)
                if match_result:
                    self.name = match_result[0]
                    LOGGER.info(
                        f"Matched command '{self.command}' to parser: {self.name}"
                    )
                    break
            except re.error as e:
                LOGGER.error(
                    f"Regex error in parser '{parser_name}': {e}. "
                    f"Check that all imported libraries are in SKIP_ATTRS."
                )
                raise Exception(
                    f"Parser configuration error in '{parser_name}'. "
                    f"Ensure all imported libraries are added to SKIP_ATTRS."
                )

        # Validate that a parser was found
        if not self.name:
            raise NotImplementedError(
                f"No parser found for command '{self.command}' "
                f"on platform '{self.device_os}'"
            )

        # Parse the raw output
        self._parse_output()

    def _import_parser_module(self, parser_name: str) -> Dict[str, Any]:
        """
        Import a parser module and extract its parser functions.

        Args:
            parser_name: Name of the parser module (without .py extension)

        Returns:
            Dictionary of parser functions
        """
        module_path = f'common.parsers.platforms.{self.device_os}.{parser_name}'

        try:
            self.package = importlib.import_module(module_path)
            LOGGER.debug(f"Imported parser module: {module_path}")
        except ImportError as e:
            LOGGER.error(f"Failed to import parser module '{module_path}': {e}")
            raise

        # Extract parser functions (skip private and built-in attributes)
        parser_locals = {
            attr: getattr(self.package, attr)
            for attr in dir(self.package)
            if attr not in self.SKIP_ATTRS and not attr.startswith('_')
        }

        LOGGER.debug(
            f"Extracted {len(parser_locals)} parser functions from {parser_name}"
        )
        return parser_locals

    def _parse_output(self) -> None:
        """Parse the raw output using the matched parser function."""
        try:
            parser_function = getattr(self.package, self.name)
            self.parsed = parser_function(self.raw_output)
            LOGGER.info(f"Output parsed successfully using: {self.name}")
        except Exception as e:
            LOGGER.error(f"Failed to parse output with parser '{self.name}': {e}")
            raise

    @staticmethod
    def match(
        command: str,
        locals_dict: Dict[str, Any]
    ) -> Optional[Tuple[str, Dict[str, str]]]:
        """
        Match a command string to a parser function based on docstrings.

        Args:
            command: Command string to match
            locals_dict: Dictionary of parser functions with docstrings

        Returns:
            Tuple of (parser_name, matched_parameters) or None if no match
        """
        # Get supported commands from parser docstrings
        parsers_dict = Parser._get_supported_commands(locals_dict)

        if not parsers_dict:
            LOGGER.warning("No parsers with valid docstrings found")
            return None

        LOGGER.debug(f"Supported commands:\n{json_dumps(parsers_dict, indent=2)}")

        # Try to match command to parser patterns
        parser_matched = None
        max_length = 0

        for parser_command, parser_name in parsers_dict.items():
            # Handle exact matches (no parameters)
            if '{' not in parser_command:
                if parser_command == command.strip():
                    parser_matched = (parser_name, {})
                    break
                continue

            # Handle parameterized matches
            match_result = Parser._match_parameterized_command(
                command, parser_command, parser_name, max_length
            )

            if match_result:
                new_max_length, new_match = match_result
                if new_max_length > max_length:
                    max_length = new_max_length
                    parser_matched = new_match

        return parser_matched

    @staticmethod
    def _get_supported_commands(locals_dict: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract supported commands from parser function docstrings.

        Args:
            locals_dict: Dictionary of parser functions

        Returns:
            Dictionary mapping command patterns to parser names
        """
        parsers_dict = {}

        for parser_name, parser_func in locals_dict.items():
            if not callable(parser_func) or not parser_func.__doc__:
                continue

            # Parse docstring for command patterns (format: "* command pattern")
            docstring_lines = parser_func.__doc__.strip().split('\n')

            for line in docstring_lines:
                line = line.strip()
                if line.startswith('*'):
                    # Extract command pattern
                    command_pattern = line.replace('*', '', 1).strip()
                    if command_pattern:
                        parsers_dict[command_pattern] = parser_name

        # Sort by command length (longest first) to match most specific patterns first
        return dict(
            sorted(
                parsers_dict.items(),
                key=lambda x: (x[0].split('{')[0], len(x[0])),
                reverse=True
            )
        )

    @staticmethod
    def _match_parameterized_command(
        command: str,
        parser_command: str,
        parser_name: str,
        current_max_length: int
    ) -> Optional[Tuple[int, Tuple[str, Dict[str, str]]]]:
        """
        Match a command against a parameterized parser pattern.

        Args:
            command: Command to match
            parser_command: Parser command pattern with parameters
            parser_name: Name of the parser function
            current_max_length: Current maximum match length

        Returns:
            Tuple of (match_length, (parser_name, parameters)) or None
        """
        # Extract parameters from pattern (e.g., {vrf}, {instance})
        parameters = re.findall(r'\{.*?\}', parser_command)

        # Calculate length of non-parameter words for match quality
        non_param_words = set(parser_command.split()) - set(parameters)
        len_non_param_words = len(non_param_words)

        # Build regex pattern
        regex_pattern = Parser._build_regex_pattern(parser_command, parameters)

        # Try to match
        try:
            match = re.match(regex_pattern, command)
            if match and len_non_param_words > current_max_length:
                return (len_non_param_words, (parser_name, match.groupdict()))
        except re.error as e:
            LOGGER.warning(f"Regex error matching pattern '{regex_pattern}': {e}")

        return None

    @staticmethod
    def _build_regex_pattern(parser_command: str, parameters: list) -> str:
        """
        Build a regex pattern from a parser command template.

        Args:
            parser_command: Command pattern with parameters
            parameters: List of parameter placeholders

        Returns:
            Regex pattern string
        """
        # Escape regex special characters in the base pattern
        pattern = parser_command
        for char in ['|', '^', '(', ')']:
            pattern = pattern.replace(char, f'\\{char}')

        # Replace parameter placeholders with regex capture groups
        for param in parameters:
            param_name = param.replace('{', '').replace('}', '')

            # Use strict matching for specific parameters, greedy for others
            if param_name in Parser.STRICT_PARAMS:
                # Match non-whitespace only
                regex_param = rf'(?P<{param_name}>\S+)'
            else:
                # Match any characters (greedy)
                regex_param = rf'(?P<{param_name}>.*)'

            pattern = pattern.replace(param, regex_param)

        # Add end-of-string anchor
        pattern += ''

        return pattern

    def __repr__(self) -> str:
        """String representation of the Parser."""
        return (
            f"Parser(command='{self.command}', "
            f"device_os='{self.device_os}', "
            f"parser='{self.name}')"
        )