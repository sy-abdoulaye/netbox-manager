import re


def show_ipv4_address_iosxe(output):
    """
    Parse of command:
        * show ip interface brief

    Return:
        Returns list of IPv4 addresses
    """

    result = []

    p = re.compile(
        r'^(?P<intf>\S+)\s+'
        r'(?P<ip>\S+)\s+'
        r'\S+\s+\S+\s+'
        r'(?P<status>up|down)\s+'
        r'(?P<proto>up|down)'
    )

    for line in output.splitlines():
        line = line.strip()
        m = p.match(line)
        if not m:
            continue

        intf = m.group('intf')
        ip = m.group('ip')
        status = m.group('status')
        proto = m.group('proto')

        # Skip subinterfaces
        if '.' in intf:
            continue

        # Skip unassigned or down
        if ip == 'unassigned' or status != 'up' or proto != 'up':
            continue

        entry = {
            'address': ip,
            'tenant': 'demo-lab',
            'status': 'active',
            'interface': intf,
            'assigned_object_id': intf
        }

        if intf.lower().startswith('loopback'):
            entry['role'] = 'loopback'

        result.append(entry)

    return result


def show_ipv6_address_iosxe(output):
    """
    Parse of command:
        * show ipv6 interface brief

    Return:
        Returns list of IPv6 addresses
    """

    result = []

    current_intf = None
    current_status = None

    # Interface header
    p_intf = re.compile(
        r'^(?P<intf>\S+)\s+\[(?P<admin>up|administratively down|down)/(?P<oper>up|down)\]',
        re.IGNORECASE
    )

    # IPv6 address line (indented)
    p_ipv6 = re.compile(r'^(?P<addr>[0-9a-fA-F:]+)$')

    for line in output.splitlines():
        line = line.strip()

        if not line:
            continue

        # --- Interface line ---
        m_intf = p_intf.match(line)
        if m_intf:
            intf = m_intf.group('intf')
            admin = m_intf.group('admin').lower()
            oper = m_intf.group('oper').lower()

            current_intf = None
            current_status = None

            # Skip subinterfaces
            if '.' in intf:
                continue

            if admin != 'up' or oper != 'up':
                continue

            current_intf = intf
            current_status = 'active'
            continue

        # --- IPv6 address line ---
        if line == 'unassigned' or not current_intf:
            continue

        m_ip = p_ipv6.match(line)
        if not m_ip:
            continue

        addr = m_ip.group('addr')

        # Skip link-local
        if addr.lower().startswith('fe80'):
            continue

        result.append({
            'address': addr,
            'tenant': 'demo-lab',
            'status': current_status,
            'interface': current_intf,
            'assigned_object_id': current_intf
        })

    return result
