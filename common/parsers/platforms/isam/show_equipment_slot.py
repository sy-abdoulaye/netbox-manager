import re


def show_equipment_slot(output):
    """
    Docstring for show_equipment_slot
    Parse of command:
        * show equipment slot

    :param output: raw data from command output (str)

    Return:
        Returns dict with LC/RP/OTHER keys, each containing a list of modules.
        Each module entry is a dict with keys:
            - module_bay  : raw slot value (e.g. "nt-a", "lt:1/1/1")
            - module_type : actual-type value (e.g. "fant-h", "fglt-b")
            - status      : "active" or "offline"
            - node        : same as module_bay

        Slots with actual-type "empty" are skipped entirely.
    """
    modules_dict = {
        "LC": [],
        "RP": [],
        "OTHER": [],
    }

    # Data rows are space-separated (not pipe-delimited)
    # slot       actual-type  enabled  error-status  availability  restrt-cnt
    p = re.compile(
        r'^(?P<slot>\S+)\s+'
        r'(?P<actual_type>\S+)\s+'
        r'(?P<enabled>yes|no)\s+'
        r'(?P<error_status>\S+)\s+'
        r'(?P<availability>\S+)\s+'
        r'(?P<restrt_cnt>\d+)'
    )

    for line in output.splitlines():
        m = p.match(line)
        if not m:
            continue

        slot        = m.group("slot")
        actual_type = m.group("actual_type")
        enabled     = m.group("enabled")
        availability = m.group("availability")

        # Skip empty/not-installed slots
        if actual_type == "empty":
            continue

        status = "active" if (enabled == "yes" and availability == "available") else "offline"

        # Classify
        if slot.startswith("nt-"):
            key = "RP"
        elif slot.startswith("lt:"):
            key = "LC"
        else:
            key = "OTHER"

        modules_dict[key].append({
            "module_bay":  slot,
            "module_type": actual_type,
            "status":      status,
            "node":        slot,
        })

    return modules_dict