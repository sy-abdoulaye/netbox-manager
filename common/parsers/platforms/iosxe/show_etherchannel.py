import re


def show_bundle_iosxe(output):
    """
    Parser for:
        * show etherchannel summary

    Keeps only:
      - Bundles that are UP
      - Bundles with at least one active member (bndl)

    Returns:
        [
          {
            "name": "Port-channelX",
            "type": "lag",
            "enable": True,
            "members": [
              {"interface": "...", "enabled": True}
            ]
          }
        ]
    """

    ret_list = []

    # Port-channel line
    p_po = re.compile(
        r'^\s*\d+\s+'
        r'(?P<po>Po\d+)\((?P<po_state>[A-Z]+)\)\s+'
        r'\S+\s+(?P<ports>.+)$'
    )

    # Member interfaces
    p_port = re.compile(
        r'(?P<intf>\S+)\((?P<state>bndl|susp|standalone|down)\)'
    )

    for line in output.splitlines():
        line = line.strip()

        m = p_po.match(line)
        if not m:
            continue

        po_state = m.group("po_state")

        # Keep only UP bundles (RU / SU)
        if "U" not in po_state:
            continue

        members = []

        for port_match in p_port.finditer(m.group("ports")):
            state = port_match.group("state")

            members.append({
                "interface": port_match.group("intf"),
                "enabled": state == "bndl"
            })

        # Keep only bundles with at least one active member
        if not any(m["enabled"] for m in members):
            continue

        ret_list.append({
            "name": f"Port-channel{m.group('po')[2:]}",
            "type": "lag",
            "enable": True,
            "members": members
        })

    return ret_list
