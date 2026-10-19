import re


def show_ipv4_address_hvrp(output):
    """
    Parse Huawei VRP:
        * display ip interface brief

    Return:
        List of IPv4 addresses
    """

    result = []

    p = re.compile(
        r'^(?P<intf>\S+)\s+'
        r'(?P<ip>\S+)\s+'
        r'(?P<phy>up|down)\s+'
        r'(?P<proto>up|down)',
        re.IGNORECASE
    )

    for line in output.splitlines():
        line = line.strip()
        m = p.match(line)
        if not m:
            continue

        intf = m.group('intf')
        ip = m.group('ip')
        phy = m.group('phy').lower()
        proto = m.group('proto').lower()

        if not intf:
            continue

        intf = intf.capitalize()
        # Skip subinterfaces
        if '.' in intf:
            continue

        # Skip unassigned or down
        if ip.lower() == 'unassigned' or phy != 'up' or proto != 'up':
            continue

        entry = {
            'address': ip,
            'tenant': 'demo-lab',
            'status': 'active',
            'interface': intf,
            'assigned_object_id': intf
        }

        if intf.lower().startswith('loop'):
            entry['role'] = 'loopback'

        result.append(entry)

    return result


def show_ipv6_address_hvrp(output):
    """
    Parse Huawei VRP:
        * display ipv6 interface brief

    Return:
        List of IPv6 addresses
    """

    result = []

    current_intf = None
    admin_up = False
    proto_up = False

    p_intf = re.compile(
        r'^(?P<intf>\S+)\s+current state\s*:\s*(?P<state>UP|DOWN)',
        re.IGNORECASE
    )

    p_proto = re.compile(
        r'^IPv6 protocol current state\s*:\s*(?P<state>UP|DOWN)',
        re.IGNORECASE
    )

    p_ipv6 = re.compile(
        r'^(?P<addr>[0-9a-fA-F:]+/\d+)$'
    )

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        # --- Interface line ---
        m = p_intf.match(line)
        if m:
            intf = m.group('intf')
            state = m.group('state').lower()

            current_intf = None
            admin_up = False
            proto_up = False

            # Skip subinterfaces
            if '.' in intf:
                continue

            if state == 'up':
                current_intf = intf
                admin_up = True
            continue

        # --- IPv6 protocol state ---
        m = p_proto.match(line)
        if m and current_intf:
            proto_up = m.group('state').lower() == 'up'
            continue

        # --- IPv6 address ---
        if not current_intf or not admin_up or not proto_up:
            continue

        m = p_ipv6.match(line)
        if not m:
            continue

        addr = m.group('addr')

        # Skip link-local
        if addr.lower().startswith('fe80'):
            continue

        entry = {
            'address': addr,
            'tenant': 'demo-lab',
            'status': 'active',
            'interface': current_intf,
            'assigned_object_id': current_intf
        }

        if current_intf.lower().startswith('loop'):
            entry['role'] = 'loopback'

        result.append(entry)

    return result
