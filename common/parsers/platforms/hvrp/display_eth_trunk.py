import re

def show_bundle_hvrp(output):
    """
    Parser for Huawei VRP:
        * display eth-trunk

    Keeps only:
      - Eth-Trunks with Operate status = up
      - Members with state = Selected

    Returns:
        [
          {
            "name": "Eth-TrunkX",
            "type": "lag",
            "enable": True,
            "members": [
              {"interface": "...", "enabled": True}
            ]
          }
        ]
    """

    ret_list = []
    bundle_dict = None
    in_local_section = False

    p_bundle = re.compile(r'^(Eth-Trunk\d+)\'s state information is:', re.IGNORECASE)
    p_status = re.compile(r'Operate status:\s+(?P<status>\S+)', re.IGNORECASE)
    p_local = re.compile(r'^Local:\s*$', re.IGNORECASE)
    p_partner = re.compile(r'^Partner:\s*$', re.IGNORECASE)

    p_member = re.compile(
        r'^(?P<interface>\S+)\s+'
        r'(?P<state>Selected|Unselected)',
        re.IGNORECASE
    )

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        # New bundle
        m = p_bundle.match(line)
        if m:
            # Save previous bundle ONLY if UP and has active members
            if bundle_dict and bundle_dict.get("enable") and bundle_dict["members"]:
                ret_list.append(bundle_dict)

            intf = m.group(1).capitalize()
            bundle_dict = {
                "name": intf,
                "type": "lag",
                "enable": False,
                "members": []
            }
            in_local_section = False
            continue

        if not bundle_dict:
            continue

        # Bundle status
        m = p_status.search(line)
        if m:
            bundle_dict["enable"] = m.group("status").lower() == "up"
            continue

        # Section control
        if p_local.match(line):
            in_local_section = True
            continue

        if p_partner.match(line):
            in_local_section = False
            continue

        # Members (Local only, keep Selected only)
        if in_local_section:
            m = p_member.match(line)
            if m and m.group("state").lower() == "selected":
                iface = m.group("interface")

                # Remove (h), (r), (hr), etc.
                iface = re.sub(r'\([^)]*\)', '', iface)

                bundle_dict["members"].append({
                    "interface": iface,
                    "enabled": True
                })

    # Final bundle
    if bundle_dict and bundle_dict.get("enable") and bundle_dict["members"]:
        ret_list.append(bundle_dict)

    return ret_list
