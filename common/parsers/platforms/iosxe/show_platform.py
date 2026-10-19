# import re


# def show_platform_modules_iosxe(output):
#     """
#     Parse of command:
#         * show platform

#     :param output: raw data from command output

#     Return:
#         Returns the list of modules with type and status
#     """
#     modules = []

#     # Exemple de ligne:
#     # R0        ASR1000-RP3         ok, active            00:17:31
#     p = re.compile(
#         r'^(?P<slot>\S+)\s+'
#         r'(?P<type>\S+)\s+'
#         r'(?P<state>ok(?:,\s*\w+)?|empty)\s+'
#     )

#     for line in output.splitlines():
#         m = p.match(line)
#         if not m:
#             continue

#         slot = m.group("slot")
#         module_type = m.group("type")
#         raw_state = m.group("state")

#         # Ignore empty slots
#         if raw_state == "empty":
#             continue

#         # Normalisation du status
#         status = "active" if "ok" in raw_state else "offline"

#         modules.append({
#             "module_bay": slot,
#             "module_type": module_type,
#             "status": status,
#             "node": slot
#         })

#     return modules

import re

def show_platform_modules_iosxe(output):
    """
    Parse 'show platform' IOS-XE output
        * show platform

    Returns dict with LC/RP/RSP/OTHER keys,
    each containing a list of modules
    """

    modules_dict = {
        "LC": [],
        "RP": [],
        "OTHER": []
    }

    # Exemple de ligne:
    # 0         ASR1000-MIP100      ok
    # R0        ASR1000-RP3         ok, active
    # F0        ASR1000-ESP100-X    ok, active
    # P0        ASR1000X-DC-950W    ok

    p = re.compile(
        r'^(?P<slot>\S+)\s+'
        r'(?P<type>\S+)\s+'
        r'(?P<state>ok(?:,\s*\w+)?|empty)'
    )

    for line in output.splitlines():
        line = line.strip()
        m = p.match(line)
        if not m:
            continue

        slot = m.group("slot")
        module_type = m.group("type")
        raw_state = m.group("state")

        # Ignore empty slots
        if raw_state.lower() == "empty":
            continue

        # Normalisation du status
        status = "active" if "ok" in raw_state.lower() else "offline"

        # Détermination du type de module
        if slot.isdigit() or "/" in slot:
            key = "LC"
        elif slot.startswith("R"):
            key = "RP"
        else:
            key = "OTHER"

        modules_dict[key].append({
            "module_bay": slot,
            "module_type": module_type,
            "status": status,
            "node": slot
        })

    return modules_dict
