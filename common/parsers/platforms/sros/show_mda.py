import re


def show_mda_sros(output):
    """
    Parse Nokia SR OS 'show mda' output.

    Command supported:
        * show mda

    Platform:
        - Nokia 7750 SR / SR OS

    Behavior:
        - Each MDA is treated as a Line Card (LC)
        - Slot inheritance is handled when slot column is empty
        - Only operational MDAs are considered active

    Returned data structure:
        {
            "LC": [
                {
                    "module_bay": "<slot>/<mda>",
                    "module_type": "<mda type>",
                    "status": "active",
                    "node": "<slot>"
                }
            ],
        }

    Args:
        output (str): Raw CLI output of 'show mda'

    Returns:
        dict: Dictionary with LC, RP and OTHER module lists
    """

    modules = {
        "LC": []
    }

    p_mda = re.compile(
        r'^\s*(?:(?P<slot>\d+)\s+)?'
        r'(?P<mda>\d+)\s+'
        r'(?P<type>\S+)\s+'
        r'(?P<admin>up|down)\s+'
        r'(?P<oper>up|down)',
        re.IGNORECASE
    )

    current_slot = None

    for line in output.splitlines():
        line = line.rstrip()

        if (
            not line
            or line.startswith(("=", "-", "Slot", "MDA"))
        ):
            continue

        m = p_mda.match(line)
        if not m:
            continue

        # Héritage du slot si vide
        slot = m.group("slot") or current_slot
        current_slot = slot

        mda = m.group("mda")
        module_type = m.group("type")
        status = "active" if m.group("oper").lower() == "up" else "offline"

        modules["LC"].append({
            "module_bay": f"{slot}/{mda}",
            "module_type": module_type,
            "status": status,
            "node": slot
        })

    return modules
