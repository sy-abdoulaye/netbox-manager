import re


def interfaces_eth_show(output):
    """
    Docstring for interfaces_eth_show
    Parse of command:
        * interfaces/ethernet/show --slot={slot}

    :param output: raw data from command output (str)

    Return:
        Returns a dict with key "interfaces", whose value is a dict keyed by
        interface name (e.g. "10/Eth.1"), each entry containing:
            - interface   : full interface name (e.g. "10/Eth.1")
            - type        : always "physical"
            - admin_state : "up" or "admin-down"
            - oper_state  : same as admin_state (no separate oper column)
            - mtu         : int
    """
    result = {"interfaces": {}}

    # Extract slot number from the header line e.g. "Slot 10 TU40G - ..."
    slot = None
    p_slot = re.compile(r'Slot\s+(\d+)', re.IGNORECASE)

    # Match a data row: |Name|Admin|LAG|Timeout|MediaType|FlowControl|MTU|...|
    p_row = re.compile(
        r'^\|\s*(?P<name>Eth\.\d+)\s*\|'
        r'\s*(?P<admin>\S+)\s*\|'
        r'.*?\|'        # LAG
        r'.*?\|'        # Timeout
        r'.*?\|'        # Media Type
        r'.*?\|'        # Flow Control
        r'\s*(?P<mtu>\d+)\s*\|'
    )

    for line in output.splitlines():
        # Try to grab the slot from the section header
        if slot is None:
            m_slot = p_slot.search(line)
            if m_slot:
                slot = m_slot.group(1)
                continue

        m = p_row.match(line)
        if not m:
            continue

        eth_name   = m.group("name").strip()
        admin      = m.group("admin").strip().lower()
        mtu        = int(m.group("mtu"))

        admin_state = "up" if admin == "enable" else "admin-down"
        oper_state  = admin_state

        iface_name = f"{slot}/{eth_name}" if slot else eth_name

        result["interfaces"][iface_name] = {
            "interface":   iface_name,
            "type":        "physical",
            "admin_state": admin_state,
            "oper_state":  oper_state,
            "mtu":         mtu,
        }

    return result