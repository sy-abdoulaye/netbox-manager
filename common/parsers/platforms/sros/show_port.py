import re
import json

def show_port_nokia(output):
    """
    Parser for Nokia SR OS:
        * show port

    Returns interfaces in the same format as parsed_output.txt:
        {
            "interfaces": [
                {
                    "name": "...",
                    "type": "...",
                    "status": True/False
                }
            ]
        }
    """

    interfaces = []

    # Pattern pour les ports physiques
    p_port = re.compile(
        r'^(?P<port>\S+)\s+'
        r'(?P<admin>Up|Down)\s+'
        r'(?P<link>Yes|No)\s+'
        r'(?P<state>Up|Down)',
        re.IGNORECASE
    )

    for line in output.splitlines():
        # Skip separator lines
        if line.startswith('===') or line.startswith('---'):
            continue

        # Skip header lines
        if 'Ports on Slot' in line:
            continue
        if 'Port' in line and 'Admin' in line and 'State' in line:
            continue

        # Skip empty lines
        if not line.strip():
            continue

        # Match port line
        m = p_port.match(line.strip())
        if m:
            port_name = m.group("port")
            port_state = m.group("state").lower()

            # Determine status (Up = True, Down = False)
            status = (port_state == "up")

            # Determine type based on port name and line content
            port_type = determine_port_type(port_name, line)

            interfaces.append({
                "name": port_name,
                "type": port_type,
                "status": status
            })

    return {"interfaces": interfaces}


def determine_port_type(port_name, line):
    """
    Determine the port type based on the port name and line content.
    """
    # Virtual ports (vport)
    if 'vport' in line.lower():
        return "virtual"

    # Check for specific port types in the line
    if 'cgige' in line.lower():  # 100G ports
        if '100gbase-lr4' in line.lower() or '100g-lr' in line.lower():
            return "100gbase-x-qsfp28"
        return "100gbase-x-qsfp28"

    if 'xgige' in line.lower():  # 10G ports
        if '10gbase-lr' in line.lower():
            return "10gbase-x-sfpp"
        return "10gbase-x-sfpp"

    if 'faste' in line.lower():  # Fast Ethernet
        return "1000base-t"

    # Check for LAG
    if 'lag/' in line.lower() or port_name.startswith('lag-'):
        return "lag"

    # Check port naming convention
    if '/' in port_name:
        # Channels (c) are typically 100G
        if '/c' in port_name.lower():
            return "100gbase-x-qsfp28"
        # Regular numbered ports
        parts = port_name.split('/')
        if len(parts) >= 2:
            # Slot 5 ports are typically 10G
            if parts[0] == '5':
                return "10gbase-x-sfpp"

    # Default
    return "other"

