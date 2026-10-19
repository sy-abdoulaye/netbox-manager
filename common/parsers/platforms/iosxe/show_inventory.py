import re


def normalize_name(name: str) -> str:
    name = name.strip()

    # Chassis
    if name.lower() == "chassis":
        return "Rack 0"

    # module X
    m = re.match(r"module (\d+)", name, re.IGNORECASE)
    if m:
        return m.group(1)

    # module R0 / F0
    m = re.match(r"module ([RF])(\d+)", name, re.IGNORECASE)
    if m:
        typ, idx = m.groups()
        if typ.upper() == "R":
            return f"R{idx}"
        if typ.upper() == "F":
            return f"0/ESP{idx}"

    # SPA subslot X/Y
    m = re.match(r"SPA subslot (\d+)/(\d+)", name, re.IGNORECASE)
    if m:
        return f"{m.group(1)}/{m.group(2)}"

    # transceiver
    m = re.match(r"subslot (\d+)/(\d+) transceiver (\d+)", name, re.IGNORECASE)
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"

    # Power Supply
    m = re.match(r"Power Supply Module (\d+)", name, re.IGNORECASE)
    if m:
        return f"P{m.group(1)}"

    # Fan Tray
    m = re.match(r"Fan Tray (\d+)", name, re.IGNORECASE)
    if m:
        return f"F{m.group(1)}"

    return name  # fallback


def parse_show_inventory(output: str) -> dict:
    """Parse the output of 'show inventory' command and return a structured inventory dictionary.
    show inventory output example:
    * show inventory
    NAME: "Chassis", DESCR: "Cisco ASR 1001-X Chassis", PID: ASR1001-X, VID: V01, SN: FOC12345678
    NAME: "module 0", DESCR: "Cisco ASR 1001-X Route Processor", PID: ASR1001-RP, VID: V01, SN  : FOC12345679
    NAME: "module 1", DESCR: "Cisco ASR 1001-X SPA Interface Processor", PID: ASR1001-ESP, VID: V01, SN:        FOC12345680
    ...
    ...
    ...
    NAME: "subslot 1/0 transceiver 0", DESCR: "Cisco ASR 1001-X SFP-10G-LR", PID: SFP-10G-LR, VID: V01, SN: FOC12345681
    NAME: "Power Supply Module 0", DESCR: "Cisco ASR 1001-X Power Supply", PID: ASR1001-PS, VID: V01, SN: FOC12345682

    The function uses regular expressions to extract relevant information such as name, description,
    product ID, version ID, and serial number from the command output. The extracted data is then
    organized into a nested dictionary structure for easy access and further processing.
    """
    inventory = {"module_name": {}}

    pattern = re.compile(
        r'NAME:\s*"(?P<name>.*?)",\s*DESCR:\s*"(?P<descr>.*?)"\s*'
        r'PID:\s*(?P<pid>[^,]+),\s*VID:\s*(?P<vid>[^,]+),\s*SN:\s*(?P<sn>\S+)',
        re.DOTALL
    )

    for match in pattern.finditer(output):
        raw_name = match.group("name").strip()
        name = normalize_name(raw_name)

        inventory["module_name"][name] = {
            "descr": match.group("descr").strip(),
            "pid": match.group("pid").strip(),
            "vid": match.group("vid").strip(),
            "sn": match.group("sn").strip(),
        }

    return inventory