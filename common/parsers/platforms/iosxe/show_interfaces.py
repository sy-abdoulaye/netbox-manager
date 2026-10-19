import re


def parse_iosxe_interface_summary_up_only(output):
    """
    Parse 'show interface summary' IOS-XE
    Return ONLY interfaces that are UP (*)
        * show interfaces summary

    Same logical output as IOS-XR parser
    """

    interfaces = []
    seen = set()

    # Match ONLY lines starting with '*'
    p = re.compile(
        r'^\*\s+'
        r'(?P<intf>'
        r'(Te|Fo|Hu|Gi|Port-channel|Loopback|Virtual-Template)'
        r'[A-Za-z0-9/]+)'
    )

    for line in output.splitlines():
        line = line.rstrip()

        if not line or line.startswith(("Interface", "---")):
            continue

        # Ignore subinterfaces
        if '.' in line:
            continue

        m = p.match(line)
        if not m:
            continue

        raw_name = m.group("intf")
        m = re.search(r'([\d/]+)$', raw_name)
        numbers = m.group(1) if m else ""
        if not numbers:
            continue

        # ---- Type mapping (XR-aligned) ----
        if raw_name.startswith("Te"):
            name = f"TenGigabitEthernet{numbers}"
            iface_type = "10gbase-x-sfpp"
        elif raw_name.startswith("Hu"):
            name = f"HundredGigabitEthernet{numbers}"
            iface_type = "100gbase-x-qsfp28"
        elif raw_name.startswith("Fo"):
            name = f"FourHundredGigabitEthernet{numbers}"
            iface_type = "400gbase-x-qsfp112"
        elif raw_name.startswith("Gi"):
            name = f"GigabitEthernet{numbers}"
            iface_type = "1000base-x-sfp"
        elif raw_name.startswith("Port-channel"):
            name = raw_name
            iface_type = "lag"
        elif raw_name.startswith("Loopback"):
            name = raw_name
            iface_type = "virtual"
        elif raw_name.startswith("Virtual-Template"):
            name = raw_name
            iface_type = "virtual"
        else:
            continue

        key = (name, iface_type)
        if key in seen:
            continue

        seen.add(key)
        interfaces.append({
            "name": name,
            "type": iface_type,
            "status": True
        })

    return {
        "interfaces": sorted(
            interfaces,
            key=lambda x: (x["type"], x["name"])
        )
    }
