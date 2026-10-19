import re


def show_chassis_power_supply_sros(output):
    """
    Parse Nokia SR OS 'show chassis power-supply' output.

    Command supported:
        * show chassis power-supply

    Platform:
        - Nokia 7750 SR / SR OS

    Behavior:
        - Extracts power supply inventory only
        - Ignores fan information
        - One entry per power supply

    Returned data structure:
        {
            "OTHER": [
                {
                    "module_bay": "PS<id>",
                    "module_type": "-",
                    "status": "active",
                    "node": "<id>"
                }
            ]
        }

    Args:
        output (str): Raw CLI output of 'show chassis power-supply'

    Returns:
        dict: Dictionary with LC, RP and OTHER module lists
    """

    modules = {
        "OTHER": []
    }

    p_ps_number = re.compile(
        r'Power supply number\s*:\s*(?P<id>\d+)',
        re.IGNORECASE
    )

    p_ps_status = re.compile(
        r'Status\s*:\s*(?P<status>up|down)',
        re.IGNORECASE
    )

    current_ps = None

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        m_num = p_ps_number.search(line)
        if m_num:
            current_ps = m_num.group("id")
            continue

        m_status = p_ps_status.search(line)
        if m_status and current_ps:
            status = "active" if m_status.group("status").lower() == "up" else "offline"

            modules["OTHER"].append({
                "module_bay": f"PS{current_ps}",
                "module_type": "-",
                "status": status,
                "node": current_ps
            })

            current_ps = None

    return modules


def show_chassis_environment_sros(output):
    """
    Parse Nokia SR OS 'show chassis environment' output.

    Command supported:
        * show chassis environment

    Platform:
        - Nokia 7750 SR / SR OS

    Behavior:
        - Extracts fan tray information only
        - Status is normalized to 'active' if up, 'offline' if down
        - Each fan tray is a separate entry in OTHER

    Returned data structure:
        {
            "OTHER": [
                {
                    "module_bay": "FAN<id>",
                    "module_type": "-",
                    "status": "active",
                    "node": "<id>"
                }
            ]
        }

    Args:
        output (str): Raw CLI output of 'show chassis environment'

    Returns:
        dict: Dictionary with LC, RP and OTHER module lists
    """

    modules = {
        "OTHER": []
    }

    # Regex pour détecter le numéro de fan tray
    p_fan_number = re.compile(
        r'Fan tray number\s*:\s*(?P<id>\d+)',
        re.IGNORECASE
    )

    # Regex pour le status du fan
    p_fan_status = re.compile(
        r'Status\s*:\s*(?P<status>up|down)',
        re.IGNORECASE
    )

    current_fan = None

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        m_num = p_fan_number.search(line)
        if m_num:
            current_fan = m_num.group("id")
            continue

        m_status = p_fan_status.search(line)
        if m_status and current_fan:
            status = "active" if m_status.group("status").lower() == "up" else "offline"

            modules["OTHER"].append({
                "module_bay": f"FAN{current_fan}",
                "module_type": "-",
                "status": status,
                "node": current_fan
            })

            current_fan = None

    return modules
