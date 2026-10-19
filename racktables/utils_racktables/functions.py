"""
RackTables Extraction Utilities

This module contains utility functions and classes for extracting data from RackTables.
"""

import ipaddress
import json
import logging
from pathlib import Path

import MySQLdb
import MySQLdb.cursors
import yaml

logger = logging.getLogger(__name__)


# -------------------------------
# Constants
# -------------------------------

# Dictionary for RackTables prefix by type (for reference)
TYPE_PREFIX_MAP = {
    "Router": "SR",
    "Server": "SV",
    "Network switch": "SW",
    "BlackBox": "BB",
    "PDU": "PDU",
    "Rack": "RK",
}


# -------------------------------
# Database Connection
# -------------------------------

def create_db_connection(db_params: dict):
    """
    Establishes and returns a MySQL database connection and cursor
    using parameters from the YAML configuration.

    Returns: (db, cursor) or (None, None) if connection fails.
    """
    db = None
    cursor = None

    if not db_params:
        logger.error("❌ Database parameters missing or not loaded.")
        return None, None

    try:
        db = MySQLdb.connect(
            host=db_params.get("host"),
            port=db_params.get("port"),
            user=db_params.get("user"),
            passwd=db_params.get("password"),
            db=db_params.get("db_name"),
            # Use DictCursor for easy dictionary access
            cursorclass=MySQLdb.cursors.DictCursor
        )
        logger.info("✅ Database connection established successfully.")

        cursor = db.cursor()
        logger.info("✅ Database cursor created.")

        return db, cursor

    except MySQLdb.Error as e:
        logger.critical(f"❌ FATAL: Failed to connect to database: {e}")
        # Close connection if it partially opened
        if db:
            db.close()
        return None, None


# -------------------------------
# YAML Configuration Loading
# -------------------------------

def load_yaml_config(filename: str, config_name: str, subdir: str = "data", base_path: Path = None) -> dict:
    """
    Loads and returns the content of a YAML configuration file from a specified subdirectory.

    Args:
        filename: Name of the YAML file (e.g., "db_config.yaml").
        config_name: Name of the configuration for log messages (e.g., "DB configuration").
        subdir: The subdirectory containing the file (e.g., "data" or "config").
        base_path: Base path for the file. If None, uses the racktables directory (parent of utils).
    """
    if base_path is None:
        # Go up one level from utils/ to racktables/
        base_path = Path(__file__).parent.parent

    yaml_path = base_path / subdir / filename
    logger.info(f"📋 Loading {config_name} from: {yaml_path}")

    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        logger.info(f"✅ {config_name.capitalize()} successfully loaded from: {filename}")
        return data
    except FileNotFoundError:
        logger.error(f"❌ File not found in '{subdir}/': {yaml_path}")
        return {}
    except yaml.YAMLError as exc:
        logger.error(f"❌ Error during YAML parsing in {filename}: {exc}")
        return {}


# -------------------------------
# Device Role Detection
# -------------------------------

def get_device_role(device_name: str, roles_config: dict) -> tuple:
    """
    Returns the device role based on its name.

    Args:
        device_name: The name of the device to check.
        roles_config: Dictionary mapping roles to patterns.

    Returns: (role, pattern) or (None, None) if no match
    """
    for role, patterns in roles_config.items():
        for pattern in patterns:
            if pattern in device_name:
                return role, pattern
    return None, None


# -------------------------------
# ID Formatting
# -------------------------------

def format_object_id(object_id: int) -> str:
    """Returns the formatted ID as in RackTables UI (always IV)"""
    return f"IV{object_id:06d}"


# -------------------------------
# IP Address Conversion
# -------------------------------

def int_to_ip(ip_int: int) -> str:
    """Converts an integer to IPv4 dotted notation string."""
    return ".".join([
        str((ip_int >> 24) & 0xFF),
        str((ip_int >> 16) & 0xFF),
        str((ip_int >> 8) & 0xFF),
        str(ip_int & 0xFF)
    ])


def bin_to_ipv6(ip_bin) -> str | None:
    """Converts a binary field (16 bytes) or hexadecimal to readable IPv6"""
    if ip_bin is None:
        return None
    try:
        # MySQL case: binary field (bytes)
        if isinstance(ip_bin, (bytes, bytearray)):
            return str(ipaddress.IPv6Address(ip_bin))
        # MySQL case: hexadecimal string (e.g., '20010db800000000...')
        elif isinstance(ip_bin, str) and len(ip_bin) == 32:
            return str(ipaddress.IPv6Address(int(ip_bin, 16)))
        else:
            # Last resort: direct attempt
            return str(ipaddress.IPv6Address(ip_bin))
    except Exception:
        return None


# -------------------------------
# Exporter Class
# -------------------------------

class RacktablesExporter:
    """Handles exporting RackTables data to various formats."""

    @staticmethod
    def get_port_type_mapping(db):
        """
        Retrieves port type mappings from the database.

        Returns: (VIRTUAL_PORT_TYPES, PHYSICAL_PORT_TYPES) as sets
        """
        cur = db.cursor(MySQLdb.cursors.DictCursor)
        cur.execute("SELECT DISTINCT type FROM Port")
        all_types = {row['type'] for row in cur.fetchall()}
        VIRTUAL_PORT_TYPES = {1469}  # known in advance
        PHYSICAL_PORT_TYPES = all_types - VIRTUAL_PORT_TYPES
        return VIRTUAL_PORT_TYPES, PHYSICAL_PORT_TYPES

    @staticmethod
    def export_json(filename: str, data: dict, results_dir: Path = None):
        """
        Exports data to a JSON file in the results directory.

        Args:
            filename: Name of the output file.
            data: Dictionary to export.
            results_dir: Directory for output. If None, uses racktables/results.
        """
        if results_dir is None:
            # Go up one level from utils/ to racktables/
            results_dir = Path(__file__).parent.parent / "results"

        # Create results folder if it doesn't exist
        results_dir.mkdir(exist_ok=True)

        # Full file path
        filepath = results_dir / filename

        with open(filepath, "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        logger.info(f"✅ Export completed → {filepath}")


# -------------------------------
# HW Type Mapping
# -------------------------------

def parse_racktables_hw_type(hw_type_raw: str) -> str:
    """
    Parse RackTables HW type format and extract the model name.

    Handles formats like:
    - "[[Cisco%GPASS%ASR 9010 | http://...]]"
    - "Cisco%GPASS%ASR 9001"
    - "Cisco%GPASS% ASR 9000v"
    - "ALU%GPASS% 7750"

    Returns: Extracted model name (e.g., "ASR 9010", "7750")
    """
    if not hw_type_raw:
        return ""

    # Remove wiki-style link brackets
    value = hw_type_raw.strip()
    if value.startswith("[[") and "]]" in value:
        # Extract content before the pipe (URL part)
        value = value[2:].split("|")[0].strip()

    # Split by %GPASS% and take the model part
    if "%GPASS%" in value:
        parts = value.split("%GPASS%")
        if len(parts) >= 2:
            model = parts[1].strip()
            return model

    return value


def load_device_types_from_yaml(models_dir: Path = None) -> dict:
    """
    Load all device types from YAML files in models/devices-types/.

    Returns: Dict mapping normalized model names to their YAML model values
             e.g., {"asr-9006": "ASR-9006", "ncs-5508": "NCS-5508"}
    """
    if models_dir is None:
        # Go up two levels from utils/ to project root, then to models/devices-types/
        models_dir = Path(__file__).parent.parent.parent / "models" / "devices-types"

    device_types = {}

    if not models_dir.exists():
        logger.warning(f"⚠️ Device types directory not found: {models_dir}")
        return device_types

    for yaml_file in models_dir.rglob("*.yaml"):
        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                if data and "model" in data:
                    model = data["model"]
                    # Store with normalized key (lowercase, spaces removed)
                    normalized = model.lower().replace(" ", "-").replace("_", "-")
                    device_types[normalized] = model
        except Exception as e:
            logger.debug(f"Could not parse {yaml_file}: {e}")

    logger.info(f"📦 Loaded {len(device_types)} device types from YAML files")
    return device_types


def normalize_hw_type(
    hw_type_raw: str,
    static_mapping: dict,
    yaml_device_types: dict,
    device_name: str = None,
    name_patterns: dict = None,
    normalization_log: list = None
) -> str:
    """
    Normalize HW type from RackTables to match NetBox device types.

    Args:
        hw_type_raw: Raw HW type value from RackTables
        static_mapping: Static mapping from hw-type-mapping.yaml (devices_types_mapping)
        yaml_device_types: Dict of device types loaded from YAML files
        device_name: Device name (used to deduce HW type if raw is empty)
        name_patterns: Dict mapping name patterns to HW types (name_to_hwtype_patterns)
        normalization_log: Optional list to append normalization info for logging

    Returns: Normalized device type name or original value if no match
    """
    # Parse the raw value
    parsed = parse_racktables_hw_type(hw_type_raw)

    # If HW type is empty, try to deduce from device name
    if not parsed and device_name and name_patterns:
        device_name_upper = device_name.upper()
        for pattern, hw_type in name_patterns.items():
            if pattern.upper() in device_name_upper:
                logger.debug(f"HW type deduced from name: {device_name} -> {hw_type} (pattern: {pattern})")
                if normalization_log is not None:
                    normalization_log.append({
                        "device_name": device_name,
                        "original_hw_type": hw_type_raw or "(empty)",
                        "normalized_hw_type": hw_type,
                        "method": f"deduced_from_name (pattern: {pattern})"
                    })
                return hw_type
        # No pattern matched
        logger.debug(f"No HW type pattern matched for device: {device_name}")
        if normalization_log is not None:
            normalization_log.append({
                "device_name": device_name,
                "original_hw_type": "(empty)",
                "normalized_hw_type": "(no match)",
                "method": "no_hw_type_no_pattern"
            })
        return hw_type_raw or ""

    if not parsed:
        return hw_type_raw or ""

    # Create normalized version for matching
    normalized = parsed.upper().replace(" ", "-").replace("_", "-")

    # 1. Check static mapping first (priority)
    if normalized in static_mapping:
        result = static_mapping[normalized]
        if normalization_log is not None and result != parsed:
            normalization_log.append({
                "device_name": device_name,
                "original_hw_type": hw_type_raw,
                "normalized_hw_type": result,
                "method": "static_mapping"
            })
        return result

    # Also check with original parsed value
    for key, value in static_mapping.items():
        if key.upper() == normalized:
            if normalization_log is not None and value != parsed:
                normalization_log.append({
                    "device_name": device_name,
                    "original_hw_type": hw_type_raw,
                    "normalized_hw_type": value,
                    "method": "static_mapping"
                })
            return value

    # 2. Try to find in YAML device types
    normalized_lower = normalized.lower()
    if normalized_lower in yaml_device_types:
        result = yaml_device_types[normalized_lower]
        if normalization_log is not None and result != parsed:
            normalization_log.append({
                "device_name": device_name,
                "original_hw_type": hw_type_raw,
                "normalized_hw_type": result,
                "method": "yaml_device_types"
            })
        return result

    # 3. Try fuzzy match: check if normalized is contained in any YAML key
    for yaml_key, yaml_model in yaml_device_types.items():
        # Check if the model number matches (e.g., "9006" in "asr-9006")
        model_numbers = [s for s in normalized.split("-") if s.isdigit() or (s and s[0].isdigit())]
        for num in model_numbers:
            if num.lower() in yaml_key:
                # Verify manufacturer prefix matches too
                if normalized_lower.startswith(yaml_key.split("-")[0]) or yaml_key.startswith(normalized_lower.split("-")[0]):
                    if normalization_log is not None and yaml_model != parsed:
                        normalization_log.append({
                            "device_name": device_name,
                            "original_hw_type": hw_type_raw,
                            "normalized_hw_type": yaml_model,
                            "method": f"fuzzy_match (yaml_key: {yaml_key})"
                        })
                    return yaml_model

    # 4. No match found, return the parsed (cleaned) value
    logger.debug(f"No mapping found for HW type: {hw_type_raw} -> {parsed}")
    if normalization_log is not None and parsed != hw_type_raw:
        normalization_log.append({
            "device_name": device_name,
            "original_hw_type": hw_type_raw,
            "normalized_hw_type": parsed,
            "method": "parsed_only"
        })
    return parsed
