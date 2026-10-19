import re

def show_lag_description_nokia(output):
    """
    Parser for Nokia SR OS:
        * show lag description

    Returns ALL LAGs and ALL members regardless of status.

    Returns:
        [
          {
            "name": "lag-X",
            "type": "lag",
            "enable": True/False,
            "description": "...",
            "lacp_enabled": True/False,
            "members": [
              {"interface": "...", "enabled": True/False}
            ]
          }
        ]
    """

    ret_list = []
    bundle_dict = None

    # Patterns
    p_lag_header = re.compile(r'^(lag-\d+)$', re.IGNORECASE)
    p_lag_status = re.compile(
        r'^(?P<id>\d+)\((?P<lacp>[ed])\)\s+'
        r'(?P<adm>\S+)\s+'
        r'(?P<opr>\S+)\s+'
        r'(?P<desc>.*)',
        re.IGNORECASE
    )
    p_member = re.compile(
        r'^\s+(?P<interface>\S+)\s+'
        r'(?P<adm>\S+)\s+'
        r'(?P<act_stdby>\S+)\s+'
        r'(?P<opr>\S+)',
        re.IGNORECASE
    )

    for line in output.splitlines():
        # Skip separator lines
        if line.startswith('===') or line.startswith('---'):
            continue

        # Skip header lines
        if 'Lag Port States' in line or 'LACP Status' in line:
            continue
        if line.strip().startswith('Name') or line.strip().startswith('Id'):
            continue

        # Skip empty lines
        if not line.strip():
            continue

        # New LAG header (lag-XX)
        m = p_lag_header.match(line.strip())
        if m:
            # Save previous bundle (always, no filter)
            if bundle_dict:
                ret_list.append(bundle_dict)

            lag_name = m.group(1)
            bundle_dict = {
                "name": lag_name,
                "type": "lag",
                "enable": False,
                "description": "",
                # "lacp_enabled": False,
                "members": []
            }
            continue

        if not bundle_dict:
            continue

        # LAG status line (ID(e/d) Adm Opr Description)
        m = p_lag_status.match(line.strip())
        if m:
            opr_status = m.group("opr").strip().lower()
            bundle_dict["enable"] = (opr_status == "up")

            # # LACP status (e=enabled, d=disabled)
            # lacp = m.group("lacp").strip().lower()
            # bundle_dict["lacp_enabled"] = (lacp == "e")

            # Extract description
            desc = m.group("desc").strip()
            if desc and desc != "N/A":
                bundle_dict["description"] = desc
            continue

        # Member port line (keep ALL members)
        m = p_member.match(line)
        if m:
            act_stdby = m.group("act_stdby").strip().lower()
            opr_status = m.group("opr").strip().lower()

            iface = m.group("interface").strip()

            # Member is enabled if active and up
            member_enabled = (act_stdby == "active" and opr_status == "up")

            bundle_dict["members"].append({
                "interface": iface,
                "enabled": member_enabled,
                # "admin_state": m.group("adm").strip().lower(),
                # "act_stdby": act_stdby,
                # "oper_state": opr_status
            })
            continue

    # Final bundle (always add, no filter)
    if bundle_dict:
        ret_list.append(bundle_dict)

    return ret_list

