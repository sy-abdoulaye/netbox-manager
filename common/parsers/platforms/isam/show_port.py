import re


def show_port(output):
    """
    Docstring for show_port
    Parse of command (Nokia ISAM / 7330):
        # * show port

    :param output: raw data from command output (str)

    Return:
        Returns a dict with key "interfaces", whose value is a dict keyed by
        Port Id (e.g. "nt-a:eth:1", "lt:1/1/3"), each entry containing:
            - interface   : Port Id (e.g. "nt-a:qsfp:1-1")
            - type        : always "physical"
            - admin_state : "up" or "admin-down"  (Admin State column)
            - oper_state  : "up" or "down"         (Port State column)
            - mtu         : int  (Oper MTU column)
    """
    result = {"interfaces": {}}

    # Columns: PortId  AdminState  Link  PortState  CfgMTU  OperMTU  LAG  Mode  Encp  Type
    p = re.compile(
        r'^(?P<port_id>\S+)\s+'
        r'(?P<admin>Up|Down)\s+'
        r'(?P<link>Yes|No)\s+'
        r'(?P<port_state>Up|Down)\s+'
        r'(?P<cfg_mtu>\d+)\s+'
        r'(?P<oper_mtu>\d+)\s+'
        r'(?P<lag>\S+)\s+'
        r'(?P<mode>\S+)\s+'
        r'(?P<encp>\S+)\s+'
        r'(?P<ptype>\S+)'
    )

    for line in output.splitlines():
        m = p.match(line)
        if not m:
            continue

        port_id    = m.group("port_id")
        admin      = m.group("admin")
        port_state = m.group("port_state")
        oper_mtu   = int(m.group("oper_mtu"))

        admin_state = "up" if admin=="Up" else "admin-down"
        oper_state  = "up" if port_state=="Up" else "down"

        result["interfaces"][port_id] = {
            "interface":   port_id,
            "type":        "physical",
            "admin_state": admin_state,
            "oper_state":  oper_state,
            "mtu":         oper_mtu,
        }

    return result


# Mapping Nokia port type column + port name hints → standard type string
# Priority: port name pattern first, then fallback on Nokia type column
def _resolve_type(port_id, nokia_type):
    nokia_type = nokia_type.lower()

    # Virtual ports
    if nokia_type == "vport":
        return "virtual"

    # LAG / trunk
    if nokia_type in ("lag", "trunk"):
        return "lag"

    # Line termination (DSLAM LT slots)
    if nokia_type == "lt":
        return "physical"

    # gige / xcme: refine from port name
    port_lower = port_id.lower()
    if "qsfp" in port_lower:
        return "10gbase-x-sfpp"    # QSFP used as 10G here
    if "xfp" in port_lower:
        return "10gbase-x-sfpp"
    if "sfp" in port_lower:
        return "1000base-x-sfp"
    if "eth" in port_lower or "xcme" in nokia_type:
        return "1000base-x-sfp"
    if "ieee1588" in port_lower:
        return "1000base-x-sfp"

    # Generic fallback
    return nokia_type


def show_port_brief(output):
    """
    Docstring for show_port_brief
    Parse of command:
        * show port

    :param output: raw data from command output (str)

    Return:
        Returns a dict with key "interfaces", whose value is a list of dicts,
        each containing:
            - name   : Port Id (e.g. "nt-a:qsfp:1-1", "lt:1/1/3")
            - type   : standard type string (e.g. "10gbase-x-sfpp", "virtual")
            - status : bool  (True if Port State == "Up")
    """
    result = {"interfaces": []}

    # Columns: PortId  AdminState  Link  PortState  CfgMTU  OperMTU  LAG  Mode  Encp  Type
    p = re.compile(
        r'^(?P<port_id>\S+)\s+'
        r'(?P<admin>Up|Down)\s+'
        r'(?P<link>Yes|No)\s+'
        r'(?P<port_state>Up|Down)\s+'
        r'(?P<cfg_mtu>\d+)\s+'
        r'(?P<oper_mtu>\d+)\s+'
        r'(?P<lag>\S+)\s+'
        r'(?P<mode>\S+)\s+'
        r'(?P<encp>\S+)\s+'
        r'(?P<ptype>\S+)'
    )

    seen = set()  # deduplicate (same port can appear in multiple sections)

    for line in output.splitlines():
        m = p.match(line)
        if not m:
            continue

        port_id    = m.group("port_id")
        port_state = m.group("port_state")
        nokia_type = m.group("ptype")

        if port_id in seen:
            continue
        seen.add(port_id)

        result["interfaces"].append({
            "name":   port_id,
            "type":   _resolve_type(port_id, nokia_type),
            "status": port_state == "Up",
        })

    return result
