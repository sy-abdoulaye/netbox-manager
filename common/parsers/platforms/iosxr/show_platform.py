import re


def show_platform_modules(output):
    """
    Docstring for show_platform_modules
    Parse of command:
        * show platform

    :param output: raw data from command output

    Return:
        Returns dict with LC/RP/RSP keys, each containing a list of modules
    """
    modules_dict = {
        "LC": [],
        "RP": [],
        "OTHER": []
    }
    p = re.compile(
        r'^(?P<node>\S+)\s+'
        r'(?P<type>\S+)\s+'
        r'(?P<state>IOS XR RUN|OPERATIONAL|UP|DOWN)'
    )

    p_lc = re.compile(r'\d+/\d+/CPU\d+')
    # p_rp = re.compile(r'\d+/RP\d+/CPU\d+')
    p_rp = re.compile(r'\d+/(?:RP|RSP)\d+/CPU\d+')

    for line in output.splitlines():
        m = p.match(line)
        if not m:
            continue

        node = m.group("node")
        if "/NPU" in node:
            continue

        if p_lc.match(node):
            slot = node.split("/")[1]
            module_bay = f"LC{slot}"
            key = "LC"
        elif p_rp.match(node):
            module_bay = node.split("/")[1]
            key = "RP"
        else:
            module_bay = node.split("/")[-1]
            key = "OTHER"

        raw_state = m.group("state")
        status = "active" if raw_state in ["IOS XR RUN", "OPERATIONAL", "UP"] else "offline"

        type_name = m.group("type")
        type_name = type_name.replace("(Active)", "").replace("(Standby)", "").strip()

        modules_dict[key].append({
            "module_bay": module_bay,
            "module_type": type_name,
            "status": status,
            "node": node
        })
    return modules_dict