import re

def show_router_interface_nokia(output, tenant="demo-lab"):
    """
    Parser for Nokia SR OS:
        * show router interface

    Returns only interfaces with Mode = Network and Port/SapId != n/a.
    Returns all IP addresses (IPv4 and IPv6) associated with each Port/SapId.

    Returns:
        [
            {
                "address": "x.x.x.x/mask",
                "tenant": "...",
                "status": "active",
                "interface": "Port/SapId",
                "assigned_object_id": "Port/SapId"
            }
        ]
    """

    result = []
    current_port = None
    current_mode = None
    current_status = None

    # Pattern pour la ligne d'interface
    p_interface = re.compile(
        r'^(?P<name>\S+)\s+'
        r'(?P<adm>Up|Down)\s+'
        r'(?P<opr>\S+)\s+'
        r'(?P<mode>\S+)\s+'
        r'(?P<port>\S+)',
        re.IGNORECASE
    )

    # Pattern pour les adresses IP (IPv4 et IPv6)
    p_ip = re.compile(
        r'^\s*(?P<ip>[0-9a-f.:]+/\d+)',
        re.IGNORECASE
    )

    for line in output.splitlines():
        # Skip separator lines
        if line.startswith('===') or line.startswith('---'):
            continue

        # Skip header lines
        if 'Interface Table' in line or 'Interface-Name' in line or 'IP-Address' in line:
            continue

        # Skip empty lines
        if not line.strip():
            continue

        # Match interface line
        m = p_interface.match(line.strip())
        if m:
            current_mode = m.group("mode")
            current_port = m.group("port")

            # Skip if Port/SapId is n/a
            if current_port.lower() == "n/a":
                current_port = None
                continue

            # Skip if Mode is not Network
            if current_mode.lower() != "network":
                current_port = None
                continue

            # Determine status based on Opr field
            opr = m.group("opr")
            # Opr format can be "Up/Down", "Up/Up", "Down/Down"
            # We consider active if at least IPv4 is Up (first part)
            current_status = "active" if opr.startswith("Up") else "reserved"

            continue

        # Match IP address line (only if we have a valid current_port)
        if current_port:
            m = p_ip.match(line)
            if m:
                ip_address = m.group("ip")

                # Skip Unnumbered interfaces
                if "Unnumbered" in line:
                    continue

                # Determine role based on interface name (for loopback)
                role = None
                if "loopback" in current_port.lower() or current_port.lower().startswith("lo"):
                    role = "loopback"

                # Create entry
                entry = {
                    "address": ip_address,
                    "tenant": tenant,
                    "status": current_status,
                    "interface": current_port,
                    "assigned_object_id": current_port
                }

                if role:
                    entry["role"] = role

                result.append(entry)

    return result
