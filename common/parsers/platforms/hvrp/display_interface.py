import re


def parsed_interfaces_brief_hvrp(output):
    """
    Parse Huawei VRP 'display interface brief'
    * display interface brief

    Rules:
      - Keep only PHY=up AND Protocol=up
      - Ignore subinterfaces
      - Normalize VRP quirks (*down, up(s), (10G))
      - If speed is explicitly present in interface name (e.g. (10G)),
        use it to force iface_type
    """

    SPEED_TO_IFACE_TYPE = {
        "1G": "1000base-x-sfp",
        "10G": "10gbase-x-sfpp",
        "25G": "25gbase-x-sfp28",
        "40G": "40gbase-x-qsfpp",
        "100G": "100gbase-x-qsfp28",
    }

    interfaces = []
    seen = set()

    line_re = re.compile(
        r'^(?P<indent>\s*)'
        r'(?P<ifname>\S+)\s+'
        r'(?P<phy>\*?up|\*?down)\s+'
        r'(?P<proto>up|down|up\(s\))',
        re.IGNORECASE
    )

    for line in output.splitlines():
        raw = line.rstrip()

        if not raw or raw.startswith(("PHY:", "Interface", "InUti", "<")):
            continue

        m = line_re.match(raw)
        if not m:
            continue

        intf = m.group("ifname")

        # Ignore subinterfaces
        if "." in intf:
            continue

        # Normalize states
        phy = m.group("phy").replace("*", "").lower()
        proto = m.group("proto").lower()
        status = phy == "up" and proto == "up"

        # Extract speed suffix like (10G)
        speed_match = re.search(r'\((\d+G)\)', intf)
        speed = speed_match.group(1) if speed_match else None

        # Remove speed suffix
        intf = re.sub(r'\(.*?\)', '', intf)

        # Extract numbers (0/3/20)
        num_match = re.search(r'([\d/]+)$', intf)
        numbers = num_match.group(1) if num_match else ""

        # ------------------------
        # Interface mapping logic
        # ------------------------

        # Priority 1: explicit speed
        if speed and speed in SPEED_TO_IFACE_TYPE:
            iface_type = SPEED_TO_IFACE_TYPE[speed]

            if intf.startswith("GigabitEthernet"):
                name = f"GigabitEthernet{numbers}"
            elif intf.startswith("XGigabitEthernet"):
                name = f"XGigabitEthernet{numbers}"
            elif intf.startswith(("100GE", "00GE")):
                name = f"HundredGigabitEthernet{numbers}"
            else:
                name = intf

        # Priority 2: infer from interface name
        elif intf.startswith(("100GE", "00GE")):
            name = f"HundredGigabitEthernet{numbers}"
            iface_type = "100gbase-x-qsfp28"

        elif intf.startswith("XGigabitEthernet"):
            name = f"XGigabitEthernet{numbers}"
            iface_type = "10gbase-x-sfpp"

        elif intf.startswith("GigabitEthernet"):
            name = f"GigabitEthernet{numbers}"
            iface_type = "1000base-x-sfp"

        elif intf.startswith("Eth-Trunk"):
            name = intf
            iface_type = "lag"

        elif intf.startswith("MEth"):
            name = intf
            iface_type = "1000base-t"

        else:
            name = intf
            iface_type = "virtual"

        key = (name, iface_type)
        if key in seen:
            continue

        seen.add(key)
        interfaces.append({
            "name": name,
            "type": iface_type,
            "status": status
        })

    return {
        "interfaces": sorted(
            interfaces,
            key=lambda x: (x["type"], x["name"])
        )
    }
