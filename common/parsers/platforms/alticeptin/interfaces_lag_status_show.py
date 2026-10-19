import re


def interfaces_lag_status_show(output):
    """
    Docstring for show_lag_status
    Parse of command:
        * interfaces/lag/status/show

    :param output: raw data from command output (str)

    Return:
        Returns a list of LAG dicts, each with keys:
            - name         : LAG name (e.g. "LAG.1")
            - type         : always "lag"
            - enable       : bool  (Admin == "enable")
            - members      : list of dicts with keys:
                - interface : Slot/Port value (e.g. "10/Eth.1")
                - enabled   : bool  (Status == "Active")

        LAGs with no member rows get an empty members list.
    """
    lags = {}       # ordered dict keyed by LAG name
    lag_order = []  # preserve insertion order

    # Match a data row: |ID|Name|Admin|LinkStatus|ChannelType|Slot/Port|Status|
    p = re.compile(
        r'^\|\s*(?P<id>\d+)\s*\|'
        r'\s*(?P<name>\S+)\s*\|'
        r'\s*(?P<admin>\S+)\s*\|'
        r'\s*(?P<link_status>\S+)\s*\|'
        r'\s*(?P<channel_type>\S+)\s*\|'
        r'\s*(?P<slot_port>\S+)\s*\|'
        r'\s*(?P<status>\S+)\s*\|'
    )

    for line in output.splitlines():
        m = p.match(line)
        if not m:
            continue

        name         = m.group("name")
        admin        = m.group("admin")
        slot_port    = m.group("slot_port")
        member_status = m.group("status")

        # Create the LAG entry on first encounter
        if name not in lags:
            lags[name] = {
                "name":    name,
                "type":    "lag",
                "enable":  admin.lower() == "enable",
                "members": [],
            }
            lag_order.append(name)

        lags[name]["members"].append({
            "interface": slot_port,
            "enabled":   member_status.lower() == "active",
        })

    return [lags[n] for n in lag_order]