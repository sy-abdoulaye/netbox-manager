import re


# Module name prefixes considered as Route Processors / Controllers
RP_MODULE_PREFIXES = ("CXO",)

# Module name prefixes considered as Line Cards
LC_MODULE_PREFIXES = ("TG", "TU", "TC", "TR", "TP")


def equipement_boards_show(output):
    """
    Docstring for equipement_boards_show
    Parse of command:
        * equipment/boards/show

    :param output: raw data from command output (str)

    Return:
        Returns dict with LC/RP/OTHER keys, each containing a list of modules.
        Each module entry is a dict with keys:
            - module_bay  : e.g. "LC1", "RP0", "FT21"
            - module_type : e.g. "CXO640G", "TG16G"
            - status      : "active" or "offline"
            - node        : e.g. "0/1", "0/RP0", "0/FT21"

        Slots with state "Empty" or "--" name are skipped entirely.
    """
    modules_dict = {
        "LC": [],
        "RP": [],
        "OTHER": [],
    }

    # Match a board data row:  |slot|name|state|...|
    # Slot is an integer, name and state are non-empty strings
    p_board = re.compile(
        r'^\|\s*(?P<slot>\d+)\s*\|'
        r'\s*(?P<name>\S+.*?)\s*\|'
        r'\s*(?P<state>\S+)\s*\|'
    )

    # Match a fan row: |slot|rpm1|rpm2|...|
    p_fan = re.compile(
        r'^\|\s*(?P<slot>\d+)\s*\|'
        r'\s*(?P<rpm>\d+)\s*\|'
    )

    for line in output.splitlines():
        # ── Fan tray rows ────────────────────────────────────────────────
        m_fan = p_fan.match(line)
        if m_fan:
            slot = m_fan.group("slot")
            modules_dict["OTHER"].append({
                "module_bay": slot,
                "module_type": "FAN",
                "status": "active",
                "node": slot,
            })
            continue

        # ── Board rows ───────────────────────────────────────────────────
        m = p_board.match(line)
        if not m:
            continue

        slot = m.group("slot")
        name = m.group("name").strip()
        state = m.group("state").strip()

        # Skip empty / absent / placeholder slots
        if name == "--" or state in ("Empty", "--"):
            continue

        # Strip role annotations like "(ACT)" or "(STB)"
        module_type = re.sub(r'\s*\(.*?\)', '', name).strip()

        # Determine status
        status = "active" if state == "OK" else "offline"

        # Classify into RP / LC / OTHER
        if module_type.startswith(RP_MODULE_PREFIXES):
            key = "RP"
        elif module_type.startswith(LC_MODULE_PREFIXES):
            key = "LC"
        else:
            key = "OTHER"

        module_bay = slot
        node = slot

        modules_dict[key].append({
            "module_bay": module_bay,
            "module_type": module_type,
            "status": status,
            "node": node,
        })

    return modules_dict
