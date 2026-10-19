import re


def display_device_pic_status(output):
    """
    Parse Huawei VRP 'display device pic-status'
    * display device pic-status
    Supports:
    - ATN / access devices
    - NE8000 / NE40
    """

    pics = []

    # --- NE8000 format (9/5)
    p_pic_ne = re.compile(
        r'^(?P<pic>\d+/\d+)\s+'
        r'(?P<status>Registered|Unregistered)\s+'
        r'(?P<type>\S+)\s+'
        r'\d+\s+'
        r'(SUCCESS|FAILED)\s+'
        r'(SUCCESS|FAILED)',
        re.IGNORECASE
    )

    # --- ATN format (slot only)
    p_pic_atn = re.compile(
        r'^(?P<slot>\d+)\s+'
        r'(?P<status>Registered|Unregistered)\s+'
        r'(?P<type>\S+)\s+'
        r'\d+\s+'
        r'(SUCCESS|FAILED)',
        re.IGNORECASE
    )

    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("-", "<", "Pic", "Slot")):
            continue

        m = p_pic_ne.match(line)
        if m:
            module = f"PIC{m.group('pic')[-1]}"
            pics.append({
                "module_bay": module,
                "module_type": m.group("type"),
                "status": "active" if m.group("status").lower() == "registered" else "offline",
                "node": module
            })
            continue

        m = p_pic_atn.match(line)
        if m:
            module = f"PIC{m.group('slot')[-1]}"
            pics.append({
                "module_bay": module,
                "module_type": m.group("type"),
                "status": "active" if m.group("status").lower() == "registered" else "offline",
                "node": module
            })

    return pics


# def show_platform_modules_hvrp(output):
#     """
#     Parse Huawei VRP 'display device' (NE8000 / NE40)
#     * display device
#     Return NetBox-like structure with RP / OTHER
#     """

#     modules = {
#         "RP": [],
#         "OTHER": []
#     }

#     p_device = re.compile(
#         r'^(?P<slot>\d+)\s+'
#         r'(?P<type>\S+)\s+'
#         r'Present\s+Registered\s+'
#         r'(?P<status>Normal|Abnormal)\s+'
#         r'(?P<role>MMB|OTHER)\s+'
#         r'\d+\s+\S+',
#         re.IGNORECASE
#     )

#     for line in output.splitlines():
#         line = line.strip()
#         if not line or line.startswith(("Slot", "---", "NetEngine")):
#             continue

#         m = p_device.match(line)
#         if not m:
#             continue

#         slot = m.group("slot")
#         hw_type = m.group("type")
#         role = m.group("role").upper()
#         status = "active" if m.group("status").lower() == "normal" else "offline"

#         if hw_type.casefold() == "pic":
#             continue

#         entry = {
#             "module_bay": f"{hw_type}{slot}",
#             "module_type": hw_type,
#             "status": status,
#             "node": slot
#         }

#         if role == "MMB":
#             modules["RP"].append(entry)
#         else:
#             modules["OTHER"].append(entry)

#     return modules

# import re


# def show_platform_modules_hvrp(output):
#     """
#     Unified Huawei VRP parser for 'display device'
#         * display device
#     Supports:
#     - NE8000 / NE40
#     - ATN
#     - S-series (campus)
#     """

#     modules = {
#         "RP": [],
#         "LC": [],
#         "OTHER": []
#     }

#     # === FORMAT NE8000 / NE40 / ATN ===
#     p_chassis = re.compile(
#         r'^(?P<slot>\d+)\s+'
#         r'(?P<type>\S+)\s+'
#         r'Present\s+Registered\s+'
#         r'(?P<status>Normal|Abnormal)\s+'
#         r'(?P<role>MMB|OTHER)\s+',
#         re.IGNORECASE
#     )

#     # === FORMAT S-SERIES (line cards, CMU, PWRx, FANx) ===
#     p_stack = re.compile(
#         r'^(?P<slot>PWR\d+|FAN\d+|CMU\d+|\d+)\s+-\s+'
#         r'(?P<type>\S+)\s+'
#         r'Present\s+PowerOn\s+Registered\s+'
#         r'(?P<status>Normal|Abnormal)\s+'
#         r'(?P<role>Master|Slave|NA)',
#         re.IGNORECASE
#     )

#     for line in output.splitlines():
#         line = line.strip()
#         if not line or line.startswith(("Slot", "-", "NetEngine", "ATN")):
#             continue

#         m = p_chassis.match(line)
#         if not m:
#             m = p_stack.match(line)

#         if not m:
#             continue

#         slot = m.group("slot")
#         hw_type = m.group("type")
#         role = m.group("role").upper()
#         status = "active" if m.group("status").lower() == "normal" else "offline"

#         # ---- module_bay & node normalization
#         if slot.isdigit():
#             module_bay = f"{slot}"
#             node = slot
#         else:
#             module_bay = slot
#             node = re.search(r'\d+', slot).group()

#         entry = {
#             "module_bay": module_bay,
#             "module_type": hw_type,
#             "status": status,
#             "node": node
#         }

#         # ---- Classification
#         if role in ("MMB", "MASTER", "SLAVE"):
#             modules["RP"].append(entry)

#         elif (
#             hw_type.upper() in ("PIC", "CXP")
#             or hw_type.upper().startswith(("LE", "LS", "LST", "LPU"))
#         ):
#             modules["LC"].append(entry)

#         else:
#             modules["OTHER"].append(entry)

#     return modules

import re


def show_platform_modules_hvrp(output):
    """
    Unified Huawei VRP parser for 'display device'
        * display device
    Supports:
    - NE8000 / NE40
    - ATN
    - S-series (campus)
    """
    modules = {"LC": [], "RP": [], "OTHER": []}

    keywords = ("NetEngine", "NE40E", "ATN")
    is_ne8000_40 = any(k in output for k in keywords)

    p_ne = re.compile(
        r'^(?P<slot>\d+)\s+'
        r'(?P<type>\S+)\s+Present\s+Registered\s+'
        r'(?P<status>Normal|Abnormal)\s+'
        r'(?P<role>MMB|OTHER)\s+'
        r'\d+\s+(?P<primary>Master|Slave|NA)',
        re.IGNORECASE
    )

    p_s = re.compile(
        r'^(?P<slot>PWR\d+|FAN\d+|CMU\d+|\d+)\s+-\s+'
        r'(?P<type>\S+)\s+Present\s+PowerOn\s+Registered\s+'
        r'(?P<status>Normal|Abnormal)\s+'
        r'(?P<role>Master|Slave|NA)',
        re.IGNORECASE
    )

    rp_index = 0

    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("Slot", "-", "<")):
            continue

        m = p_ne.match(line) if is_ne8000_40 else p_s.match(line)
        if not m:
            continue

        slot = m.group("slot")
        hw_type = m.group("type")
        role = m.group("role").upper()

        status = "active" if m.group("status").lower() == "normal" else "offline"

        node_num = re.search(r'\d+', slot).group()
        module = f"{hw_type}{slot}"
        # ================= NE8000 =================
        if is_ne8000_40:
            if hw_type == "PIC":
                modules["LC"].append({
                    "module_bay": module,
                    "module_type": hw_type,
                    "status": status,
                    "node": module
                })

            elif role == "MMB":
                modules["RP"].append({
                    "module_bay": module,
                    "module_type": hw_type,
                    "status": status,
                    "node": module
                })

            else:
                modules["OTHER"].append({
                    "module_bay": module,
                    "module_type": hw_type,
                    "status": status,
                    "node": module
                })
        # ================= S-SERIES =================
        else:
            if slot.isdigit() and hw_type.upper().startswith(("LE", "LS", "LST")):
                modules["LC"].append({
                    "module_bay": slot,
                    "module_type": hw_type,
                    "status": status,
                    "node": slot
                })

            elif role in ("MASTER", "SLAVE"):
                if slot.startswith("CMU"):
                    modules["RP"].append({
                        "module_bay": slot,
                        "module_type": hw_type,
                        "status": status,
                        "node": slot
                    })
                # else:
                #     modules["RP"].append({
                #         "module_bay": slot,
                #         "module_type": hw_type,
                #         "status": status,
                #         "node": slot
                #     })

            elif slot.startswith(("PWR", "FAN")):
                modules["OTHER"].append({
                    "module_bay": slot,
                    "module_type": hw_type,
                    "status": status,
                    "node": slot
                })

    return modules
