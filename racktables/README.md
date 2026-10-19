# RackTables Data Extractor

This module extracts device and network data from a RackTables database and exports it to JSON format for migration to NetBox.

## Directory Structure

```
racktables/
├── racktable_db_extract.py   # Main extraction script
├── README.md
├── utils/
│   ├── __init__.py           # Package exports
│   └── functions.py          # Utility functions and classes
├── config/
│   └── db_config.yaml        # Database connection configuration
├── data/
│   ├── devices-roles.yaml    # Device role patterns
│   └── valid-objects.yaml    # Valid types and tags filters
└── results/                  # Output directory (auto-created)
```

## Configuration

### Database Configuration (`config/db_config.yaml`)

```yaml
database:
  host: "your-host"
  port: 3306
  user: "your-user"
  password: "your-password"
  db_name: "racktables"
```

### Device Roles (`data/devices-roles.yaml`)

Define patterns to match device names and assign roles:

```yaml
router:
  - "SR"
  - "RTR"
switch:
  - "SW"
  - "SWITCH"
server:
  - "SRV"
  - "SERVER"
```

### Valid Filters (`data/valid-objects.yaml`)

Define which object types and tags to include in the export:

```yaml
VALID_TYPES:
  - "Router"
  - "Server"
  - "Network switch"

VALID_TAGS:
  - "Production"
  - "N"
  - "Nplus1"
```

## Usage

Run the extraction script from the `racktables` directory:

```bash
cd racktables
python racktable_db_extract.py
```

## Output Files

The script generates the following JSON files in the `results/` directory:

| File | Description |
|------|-------------|
| `racktables_map.json` | Complete hierarchical export with all attributes |
| `racktables_map_flat_netbox.json` | Flattened format optimized for NetBox import |
| `racktables_object_names.json` | Simple mapping of object IDs to names |
| `racktables_map_grouped_by_main_tag.json` | Objects grouped by main tag (N, Nplus1, etc.) |

## Data Extracted

For each device, the script extracts:

- **Basic info**: ID, name, label, type, role
- **Attributes**: All RackTables custom attributes
- **Tags**: Explicit tags assigned to the object
- **IPv4/IPv6**: IP allocations with network information
- **Interfaces**: Physical and virtual ports
- **Links**: Cable connections between ports
- **Rackspace**: Rack location (rack name, unit, position)

## Filtering Pipeline

Objects are filtered through 3 stages:

1. **Tag Filter**: Must have at least one tag from `VALID_TAGS`
2. **Type Filter**: Must match a type in `VALID_TYPES`
3. **Role Filter**: Name must contain a pattern from `devices-roles.yaml`

## Utility Functions

Available in `utils/functions.py` (imported via `from utils import ...`):

| Function | Description |
|----------|-------------|
| `create_db_connection()` | Establishes MySQL connection |
| `load_yaml_config()` | Loads YAML configuration files |
| `get_device_role()` | Determines device role from name patterns |
| `format_object_id()` | Formats ID as RackTables UI format (IVxxxxxx) |
| `int_to_ip()` | Converts integer to IPv4 string |
| `bin_to_ipv6()` | Converts binary/hex to IPv6 string |
| `RacktablesExporter` | Class for JSON export operations |

## Requirements

- Python 3.10+
- MySQLdb (`mysqlclient`)
- PyYAML

Install dependencies:

```bash
pip install mysqlclient pyyaml
```
