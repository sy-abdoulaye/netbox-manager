
import re

# Mapping état verbose → état normalisé
_STATE_MAP = {
    "up": "up",
    "down": "down",
    "administratively down": "admin-down",
}

# Préfixes courts → types d'interface (format brief)
_BRIEF_PREFIXES = ("Hu", "Te", "Gi", "Fo", "Mg")

# Noms complets → types d'interface (format verbose)
_VERBOSE_PREFIXES = ("GigabitEthernet", "HundredGigE", "TenGigE", "FortyGigE", "Management")
_MANAGEMENT_PREFIXES = ("Mg", "Management")


def _parse_brief(output: str) -> dict:
    """Parse le format 'show interfaces location <loc> brief'."""
    ret_dict = {"interfaces": {}}

    p = re.compile(
        r"^(?P<interface>(?:Hu|Te|Gi|Fo|Mg)\S+)\s+"
        r"(?P<admin_state>up|down|admin-down|err-disable)\s+"
        r"(?P<oper_state>up|down|admin-down)\s+"
        r"(?P<encap>\S+)\s+"
        r"(?P<mtu>\d+)\s+"
        r"(?P<bandwidth>\d+)$"
    )

    for line in output.splitlines():
        m = p.match(line.strip())
        if not m:
            continue
        interface = m.group("interface")
        if "." in interface:
            continue
        ret_dict["interfaces"][interface] = {
            "interface": interface,
            "type": "management" if interface.startswith("Mg") else "physical",
            "admin_state": m.group("admin_state"),
            "oper_state": m.group("oper_state"),
            "encapsulation": m.group("encap"),
            "mtu": int(m.group("mtu")),
            "bandwidth_kbps": int(m.group("bandwidth")),
        }

    return ret_dict


def _parse_verbose(output: str) -> dict:
    """Parse le format 'show interfaces location <loc>' (verbose, blocs multi-lignes)."""
    ret_dict = {"interfaces": {}}

    # Ligne d'en-tête d'interface :
    #   GigabitEthernet0/1/0/0 is administratively down, line protocol is administratively down
    p_header = re.compile(
        r"^(?P<interface>(?:"
        + "|".join(_VERBOSE_PREFIXES)
        + r")\S*)"
        r"\s+is\s+(?P<admin_state>up|down|administratively down)"
        r",\s+line protocol is\s+(?P<oper_state>up|down|administratively down)"
    )

    # MTU + BW sur la même ligne :  MTU 4014 bytes, BW 1000000 Kbit
    p_mtu_bw = re.compile(
        r"MTU\s+(?P<mtu>\d+)\s+bytes,\s+BW\s+(?P<bandwidth>\d+)\s+Kbit"
    )

    # Encapsulation (verbose) :  Encapsulation ARPA,  ou  Encapsulation 802.1Q ...
    p_encap = re.compile(r"Encapsulation\s+(?P<encap>\S+),?")

    current: dict | None = None

    for line in output.splitlines():
        line_stripped = line.strip()

        # Nouvelle interface ?
        m_header = p_header.match(line_stripped)
        if m_header:
            interface = m_header.group("interface")
            # Ignorer les sous-interfaces (ex: GigabitEthernet0/1/0/6.316)
            if "." in interface:
                current = None
                continue

            admin_state = _STATE_MAP.get(m_header.group("admin_state"), m_header.group("admin_state"))
            oper_state  = _STATE_MAP.get(m_header.group("oper_state"),  m_header.group("oper_state"))
            is_mgmt = any(interface.startswith(p) for p in _MANAGEMENT_PREFIXES)

            current = {
                "interface": interface,
                "type": "management" if is_mgmt else "physical",
                "admin_state": admin_state,
                "oper_state": oper_state,
                "encapsulation": None,
                "mtu": None,
                "bandwidth_kbps": None,
            }
            ret_dict["interfaces"][interface] = current
            continue

        if current is None:
            continue

        # MTU + BW
        if current["mtu"] is None:
            m_mtu = p_mtu_bw.search(line_stripped)
            if m_mtu:
                current["mtu"] = int(m_mtu.group("mtu"))
                current["bandwidth_kbps"] = int(m_mtu.group("bandwidth"))

        # Encapsulation
        if current["encapsulation"] is None:
            m_encap = p_encap.search(line_stripped)
            if m_encap:
                # Nettoyer la virgule éventuelle
                current["encapsulation"] = m_encap.group("encap").rstrip(",")

    return ret_dict


def show_interfaces_physical(output: str) -> dict:
    """
    Parse la sortie des commandes IOS-XR :
        * show interfaces location {location} brief
        * show interfaces location {location}

    Le format est détecté automatiquement.

    Args:
        output (str): Sortie brute de la commande CLI.

    Returns:
        dict: {
            "interfaces": {
                "<nom_interface>": {
                    "interface": str,
                    "type": str,          # "physical" ou "management"
                    "admin_state": str,   # "up" | "down" | "admin-down"
                    "oper_state": str,    # "up" | "down" | "admin-down"
                    "encapsulation": str,
                    "mtu": int,
                    "bandwidth_kbps": int
                }
            }
        }
    """
    # Détection du format : la ligne d'en-tête verbose contient " is up" ou " is down" etc.
    verbose_pattern = re.compile(
        r"^(?:" + "|".join(_VERBOSE_PREFIXES) + r")\S*\s+is\s+(?:up|down|administratively down)",
        re.MULTILINE,
    )

    if verbose_pattern.search(output):
        return _parse_verbose(output)
    else:
        return _parse_brief(output)


# def show_interfaces_physical(output):
#     """
#     Parse the output of the IOS-XR command:
#         * show interfaces location {location} brief

#     This function extracts physical and management interfaces
#     (Hu, Te, Gi, Fo, Mg) along with their main attributes.

#     Subinterfaces (e.g., Hu0/1/0/0.100) are ignored.

#     Args:
#         output (str): Raw CLI command output.

#     Returns:
#         dict: Structured dictionary containing interfaces, formatted as:
#             {
#                 "interfaces": {
#                     "<interface_name>": {
#                         "interface": str,
#                         "type": str,  # "physical" or "management"
#                         "admin_state": str,
#                         "oper_state": str,
#                         "encapsulation": str,
#                         "mtu": int,
#                         "bandwidth_kbps": int
#                     }
#                 }
#             }

#     Raises:
#         None

#     Notes:
#         - Supported interface types: Hu (HundredGigE), Te (TenGigE),
#           Gi (GigabitEthernet), Fo (FortyGigE), Mg (Management).
#         - The "type" field is automatically determined:
#             * "management" if interface starts with "Mg"
#             * otherwise "physical"
#         - Bandwidth is expressed in Kbps.

#     Example:
#         >>> output = "Hu0/1/0/0 up up ARPA 9216 100000000"
#         >>> show_interfaces_physical(output)
#         {
#             "interfaces": {
#                 "Hu0/1/0/0": {
#                     "interface": "Hu0/1/0/0",
#                     "type": "physical",
#                     "admin_state": "up",
#                     "oper_state": "up",
#                     "encapsulation": "ARPA",
#                     "mtu": 9216,
#                     "bandwidth_kbps": 100000000
#                 }
#             }
#         }
#     """

#     ret_dict = {"interfaces": {}}

#     # Interfaces physiques + management
#     p = re.compile(
#         r"^(?P<interface>(Hu|Te|Gi|Fo|Mg)\S+)\s+"
#         r"(?P<admin_state>up|down|admin-down|err-disable)\s+"
#         r"(?P<oper_state>up|down|admin-down)\s+"
#         r"(?P<encap>\S+)\s+"
#         r"(?P<mtu>\d+)\s+"
#         r"(?P<bandwidth>\d+)$"
#     )

#     for line in output.splitlines():
#         line = line.strip()

#         match = p.match(line)
#         if match:
#             interface = match.group("interface")

#             # Exclure les subinterfaces (ex: Hu0/1/0/10.100)
#             if "." in interface:
#                 continue

#             ret_dict["interfaces"][interface] = {
#                 "interface": interface,
#                 "type": "management" if interface.startswith("Mg") else "physical",
#                 "admin_state": match.group("admin_state"),
#                 "oper_state": match.group("oper_state"),
#                 "encapsulation": match.group("encap"),
#                 "mtu": int(match.group("mtu")),
#                 "bandwidth_kbps": int(match.group("bandwidth")),
#             }

#     return ret_dict

def parsed_interfaces(output):
    """
    Parse 'show interfaces brief' IOS-XR output.
    * show interfaces brief location {location}

    Supports:
      - HundredGigE (Hu)
      - FourHundredGigE (FH)
      - MgmtEth (Mg) on RP0 / RP1

    :param output: raw CLI output (str)
    :param module_placeholder: placeholder for module index
    :return: dict
    """

    interfaces = []
    seen = set()

    p = re.compile(
        r'^(?P<prefix>Hu|FH|Mg)'
        r'(?P<rack>\d+)/'
        r'(?P<slot>\d+|RP[01])/'
        r'(?P<subslot>\d+|CPU0)/'
        r'(?P<port>\d+)'
    )

    for line in output.splitlines():
        line = line.strip()

        # Ignore subinterfaces
        if '.' in line:
            continue

        m = p.match(line)
        if not m:
            continue

        prefix = m.group('prefix')
        rack = m.group('rack')
        slot = m.group('slot')
        subslot = m.group('subslot')
        port = m.group('port')

        if prefix == "Hu":
            name = f"HundredGigE{rack}/{slot}/{subslot}/{port}"
            iface_type = "100gbase-x-qsfp28"
        elif prefix == "FH":
            name = f"FourHundredGigE{rack}/{slot}/{subslot}/{port}"
            iface_type = "400gbase-x-qsfp112"
        elif prefix == "Mg":
            # slot = RP0 ou RP1
            name = f"MgmtEth0/{slot}/CPU0/{port}"
            iface_type = "1000base-t"
        else:
            continue

        key = (name, iface_type)
        if key in seen:
            continue

        seen.add(key)
        interfaces.append({
            "name": name,
            "type": iface_type
        })

    return {
        "interfaces": sorted(
            interfaces,
            key=lambda x: (x["type"], x["name"])
        )
    }


def parsed_interfaces_brief(output):
    """
    Parse 'show interfaces brief' IOS-XR output.
    Returns only interfaces that are UP, ignores subinterfaces.
        * show interfaces brief
    Supports:
      - HundredGigE (Hu)
      - FourHundredGigE (FH)
      - MgmtEth (Mg) on RP0 / RP1
      - Loopback (Lo)
      - Null (Nu)
      - Others

    :param output: raw CLI output (str)
    :return: dict {"interfaces": [{"name":..., "type":...}, ...]}
    """

    interfaces = []
    seen = set()
    numbers = ""
    # Match XR interface prefixes
    p = re.compile(
        r'^(?P<name>\S+)\s+'
        r'(?P<admin_state>\S+)\s+'
        r'(?P<oper_state>\S+)\s+'
    )

    for line in output.splitlines():
        line = line.strip()

        # Ignore subinterfaces
        if '.' in line:
            continue

        m = p.match(line)
        if not m:
            continue

        intf = m.group("name")
        admin = m.group("admin_state").lower()
        oper = m.group("oper_state").lower()
        status = True
        # Keep only interfaces UP/UP
        if admin != "up" or oper != "up":
            status = False

        match = re.search(r'([\d/]+)$', intf)
        if match:
            numbers = match.group(1) if m else ""
            if not numbers:
                continue

        # Determine interface type
        if intf.startswith("Hu"):
            name = f"HundredGigE{numbers}"
            iface_type = "100gbase-x-qsfp28"
        elif intf.startswith("Gi"):
            name = f"GigE{numbers}"
            iface_type = "1000base-lx"
        elif intf.startswith("FH"):
            name = f"FourHundredGigE{numbers}"
            iface_type = "400gbase-x-qsfp112"
        elif intf.startswith("Mg"):
            name = intf
            iface_type = "1000base-t"
        elif intf.startswith("Lo"):
            name = f"loopback{numbers}"
            iface_type = "virtual"
        elif intf.startswith(("Be", "BE")):
            name = f"Bundle-Ether{numbers}"
            iface_type = "lag"
        elif intf.startswith("TF"):
            name = f"TwentyFiveGigE{numbers}"
            iface_type = "25gbase-x-sfp28"
        elif intf.startswith("Te"):
            name = f"TenGigE{numbers}"
            iface_type = "10gbase-x-sfpp"
        else:
            name = intf
            iface_type = "other"

        key = (name, iface_type)
        if key in seen:
            continue

        seen.add(key)
        interfaces.append({
            "name": name,
            "type": iface_type,
            "status": status
        })

    return {
        "interfaces": sorted(
            interfaces,
            key=lambda x: (x["type"], x["name"])
        )
    }
