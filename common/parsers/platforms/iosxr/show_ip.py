import re

def show_ipv4_address(output):
    """
    Docstring for:
    Parse of command:
        * show ip interface brief

    :param output: raw data from command output

    Return:
        Returns dict
    """
    result = []

    # Exemple de ligne :
    # Loopback3   203.0.113.130   Up   Up   default
    p = re.compile(
        r'^(?P<intf>\S+)\s+'
        r'(?P<ip>\S+)\s+'
        r'(?P<status>Up|Down)\s+'
        r'\S+\s+'
        r'(?P<vrf>\S+)'
    )

    for line in output.splitlines():
        line = line.strip()
        m = p.match(line)

        if not m:
            continue

        status = m.group('status')
        intf = m.group('intf')
        ip = m.group('ip')
        if ip == 'unassigned' or '.' in intf or status != 'Up':
            continue

        if status == 'Up':
            status = 'active'

        entry = {
            'address': ip,
            'tenant': 'demo-lab',
            'status': status,
            'interface': intf,
            'assigned_object_id': intf
        }

        if intf.lower().startswith('loopback'):
            entry['role'] = 'loopback'

        result.append(entry)

    return result

def show_ipv6_address(output):
    """
    Parse:
        * show ipv6 interface brief
    """

    result = []

    current_intf = None
    current_status = None

    # Interface line
    p_intf = re.compile(
        r'^(?P<intf>\S+)\s+\[(?P<admin>Up|Down|Shutdown)/(?P<oper>Up|Down)\]'
    )

    # IPv6 address (any, without indentation)
    p_ipv6 = re.compile(r'^(?P<addr>[0-9a-fA-F:]+)$')

    for line in output.splitlines():
        line = line.strip()

        if not line:
            continue

        # --- Interface line ---
        m_intf = p_intf.match(line)
        if m_intf:
            intf = m_intf.group('intf')
            admin = m_intf.group('admin')
            oper = m_intf.group('oper')

            # Reset context
            current_intf = None
            current_status = None

            # Skip subinterfaces
            if '.' in intf:
                continue

            # Only Up/Up
            if admin != 'Up' or oper != 'Up':
                continue

            current_intf = intf
            current_status = 'active'
            continue

        # --- IPv6 line ---
        if line == 'unassigned':
            continue

        m_ip = p_ipv6.match(line)
        if m_ip and current_intf:
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

