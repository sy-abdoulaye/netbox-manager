import re

def show_snmp_interface(output):
    """
    Parser for Cisco IOS-XR:
        * show snmp interface

    Returns a dictionary mapping interface names to their ifIndex.

    Returns:
        {
            "interface_name": {
                "ifindex": 123
            },
            ...
        }
    """

    result = {}

    # Pattern pour extraire ifName et ifIndex
    p_interface = re.compile(
        r'ifName\s*:\s*(?P<ifname>\S+)\s+'
        r'ifIndex\s*:\s*(?P<ifindex>\d+)',
        re.IGNORECASE
    )

    for line in output.splitlines():
        # Skip empty lines
        if not line.strip():
            continue

        # Match interface line
        m = p_interface.search(line)
        if m:
            ifname = m.group("ifname")
            ifindex = int(m.group("ifindex"))

            result[ifname] = {
                "ifIndex": ifindex
            }

    return result

