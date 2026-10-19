import re

def show_bundle(output):
    """Parser for:
       * show bundle

       Keeps only:
         - bundles with Status = up
         - members with state = active

       :param output: raw data from command output
       :return: list of bundles and active members
    """

    ret_list = []
    bundle_dict = None

    # Regex
    p_bundle = re.compile(r"^(Bundle-Ether\d+)$")
    p_status = re.compile(r"^\s*Status:\s+(?P<status>\S+)", re.IGNORECASE)
    p_member = re.compile(
        r"^(?P<interface>\S+)\s+Local\s+"
        r"(?P<state>\S+)\s+.+\s+(?P<bw>\d+)$",
        re.IGNORECASE
    )

    for line in output.splitlines():
        line = line.strip()

        # Bundle name
        m = p_bundle.match(line)
        if m:
            # Save previous bundle ONLY if UP and has active members
            if bundle_dict and bundle_dict.get("enable") and bundle_dict["members"]:
                ret_list.append(bundle_dict)

            bundle_dict = {
                "name": m.group(1),
                "type": "lag",
                "enable": False,
                "members": []
            }
            continue

        if not bundle_dict:
            continue

        # Status
        m = p_status.match(line)
        if m:
            bundle_dict["enable"] = m.group("status").casefold() == "up"
            continue

        # Members (keep only active)
        m = p_member.match(line)
        if m and (m.group("state").casefold() == "active" or m.group("state").casefold() == "configured"):
            bundle_dict["members"].append({
                "interface": m.group("interface"),
                "enabled": True
            })

    # Final bundle
    if bundle_dict and bundle_dict.get("enable") and bundle_dict["members"]:
        ret_list.append(bundle_dict)

    return ret_list
