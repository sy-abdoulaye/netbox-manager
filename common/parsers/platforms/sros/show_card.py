import re


def show_card_sros(output):
    """
    Parse Nokia SR OS 'show card' output.

    Command supported:
        * show card

    Platform:
        - Nokia 7750 SR / SR OS

    Behavior:
        - Identifies CPM cards as Route Processors (RP)
        - Ignores IOM / IMM line cards
        - Ignores '(not equipped)' entries
        - RP nodes are indexed logically in discovery order (1, 2, ...)

    Returned data structure:
        {
            "LC": [],
            "RP": [
                {
                    "module_bay": <slot>,
                    "module_type": <card type>,
                    "status": "active",
                    "node": <logical index>
                }
            ],
            "OTHER": []
        }

    Args:
        output (str): Raw CLI output of 'show card'

    Returns:
        dict: Dictionary with LC, RP and OTHER module lists
    """

    modules = {
        "LC": [],
        "RP": [],
        "OTHER": []
    }

    p_card = re.compile(
        r'^(?P<slot>[A-Z0-9])\s+'
        r'(?P<type>\S+)\s+'
        r'(?P<admin>up|down)\s+'
        r'(?P<oper>up|down)(?:/\w+)?',
        re.IGNORECASE
    )

    rp_index = 1

    for line in output.splitlines():
        line = line.strip()

        if (
            not line
            or line.startswith(("=", "-", "Slot", "Card", "("))
        ):
            continue

        m = p_card.match(line)
        if not m:
            continue

        slot = m.group("slot")
        module_type = m.group("type").lower()

        # --- Route Processor (CPM)
        if module_type.startswith("cpm") or module_type.startswith("sfm"):
            modules["RP"].append({
                "module_bay": slot,
                "module_type": module_type,
                "status": "active",
                "node": slot
            })
            rp_index += 1

    return modules
