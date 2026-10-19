import json
import logging
from pathlib import Path

from .utils_racktables.functions import (
    create_db_connection,
    load_yaml_config,
    get_device_role,
    format_object_id,
    int_to_ip,
    bin_to_ipv6,
    RacktablesExporter,
    load_device_types_from_yaml,
    normalize_hw_type,
)

# -------------------------------
# Logger
# -------------------------------
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s [%(levelname)s] %(message)s"
# )
# logger = logging.getLogger(__name__)

def filter_dict_by_keywords(data: dict, keywords):
    """
    Returns a new dict containing only keys
    for which at least one value contains one of the keywords.

    :param data: dict issu du YAML {cle: [patterns]}
    :param keywords: liste des mots-clés à rechercher
    :return: dict filtré
    """
    if isinstance(keywords, str):
        keywords = [keywords]

    filtered = {}

    for key, values in data.items():
        matched_values = [
            value for value in values
            if any(f"-{keyword}-" in value for keyword in keywords)
        ]

        if matched_values:
            filtered[key] = matched_values

    return filtered


def gathering_racktables_data(logger, device_roles):
    logger.info("🚀 Starting RackTables export")

    # -------------------------------
    # Connection to Racktables DB
    # -------------------------------
    # 1. Loading from YAML the database configuration
    config_data = load_yaml_config("db_config.yaml", "DB configuration", subdir="config")

    # 2. Retrieving the connection parameters
    db_params = config_data.get("database", {})

    # 3. Establishing the connection
    db, cursor = create_db_connection(db_params)

    # 4. Checking the connection
    if cursor is None:
        logger.critical("🚨 Cannot proceed: Database cursor is unavailable. Check configuration and connection status.")

    # -------------------------------
    # Load Roles, Type & Tags
    # -------------------------------
    # 1. Load roles from devices-roles.yaml
    device_roles_data = load_yaml_config("devices-roles.yaml", "roles", subdir="data")
    # Assign the result or an empty dict to ensure DEVICE_ROLES is always a dict
    DEVICE_ROLES = device_roles_data if device_roles_data else {}

    if device_roles:
        DEVICE_ROLES = filter_dict_by_keywords(DEVICE_ROLES, device_roles)

    if DEVICE_ROLES:
        # Log the successfully loaded keys (scopes/perimeters)
        logger.info(f"✅ Roles loaded for Domaines: {list(DEVICE_ROLES.keys())}")

    # 2. Load valid types & tags from valid-objects.yaml
    valid_objects = load_yaml_config("valid-objects.yaml", "valid filters", subdir="data")

    # Injection into the variables used by the script
    # Convert list values to sets for efficient lookups
    VALID_TYPES = set(valid_objects.get("VALID_TYPES", []))
    VALID_TAGS = set(valid_objects.get("VALID_TAGS", []))

    # Log the loaded sets' counts
    logger.info(f"🎯 VALID_TYPES loaded: ({(VALID_TYPES)})")
    logger.info(f"🎯 VALID_TAGS loaded: ({(VALID_TAGS)})")

    # 3. Load HW type mappings for normalization
    hw_type_mapping_data = load_yaml_config("hw-type-mapping.yaml", "HW type mappings", subdir="data")
    DEVICES_TYPES_MAPPING = hw_type_mapping_data.get("devices_types_mapping", {})
    NAME_TO_HWTYPE_PATTERNS = hw_type_mapping_data.get("name_to_hwtype_patterns", {})
    logger.info(f"🔧 Static HW type mappings loaded: {len(DEVICES_TYPES_MAPPING)} entries")
    logger.info(f"🔧 Name-to-HW patterns loaded: {len(NAME_TO_HWTYPE_PATTERNS)} entries")

    # 4. Load device types from YAML files (models/devices-types/)
    YAML_DEVICE_TYPES = load_device_types_from_yaml()

    # -------------------------------
    # Initialize racktables_map
    # -------------------------------
    racktables_map = {}

    # -------------------------------
    # 1. Retrieve ALL objects with their tags
    # -------------------------------
    cursor.execute("""
        SELECT o.id AS object_id,
            o.name AS object_name,
            o.label AS object_label,
            o.objtype_id,
            d.dict_value AS object_type
        FROM Object o
        LEFT JOIN Dictionary d
            ON o.objtype_id = d.dict_key AND d.chapter_id = 1
    """)
    objects = cursor.fetchall()
    logger.info(f"📊 Number of objects retrieved from DB: {len(objects)}")

    rejected_by_tag = 0
    rejected_by_type = 0
    rejected_by_role = 0
    rejected_by_status = 0

    for obj in objects:
        obj_id = obj['object_id']
        obj_name = obj['object_name']
        obj_label = obj['object_label']
        obj_type = obj['object_type'] or f"Unknown({obj['objtype_id']})"

        # Generate RackTables format ID (always IV)
        formatted_id = format_object_id(obj_id)

        # -------------------------------
        # Retrieve explicit tags BEFORE filtering
        # -------------------------------
        cursor.execute("""
            SELECT tt.tag
            FROM TagStorage ts
            JOIN TagTree tt ON ts.tag_id = tt.id
            WHERE ts.entity_realm = 'object'
            AND ts.entity_id = %s
        """, (obj_id,))
        tags = [row['tag'] for row in cursor.fetchall()]

        # -------------------------------
        # FILTER 1: By Domain TAG
        # -------------------------------
        if not any(tag in VALID_TAGS for tag in tags):
            rejected_by_tag += 1
            continue

        matching_tags = [tag for tag in tags if tag in VALID_TAGS]

        # -------------------------------
        # FILTER 2: By TYPE
        # -------------------------------
        if obj_type not in VALID_TYPES:
            rejected_by_type += 1
            continue

        # -------------------------------
        # FILTER 3: By ROLE (pattern in name)
        # -------------------------------
        role, pattern = get_device_role(obj_name, DEVICE_ROLES)

        if role is None:
            logger.info(f"❌ Object rejected (no role found): name={obj_name}, type={obj_type}, tags={matching_tags}")
            rejected_by_role += 1
            continue

        # -------------------------------
        # Retrieve attributes (needed for filter 4)
        # -------------------------------
        cursor.execute("""
            SELECT a.name AS attr_name,
                a.type AS attr_type,
                av.string_value,
                av.uint_value,
                av.float_value,
                d.dict_value
            FROM AttributeValue av
            JOIN Attribute a ON av.attr_id = a.id
            LEFT JOIN Dictionary d ON av.uint_value = d.dict_key
            WHERE av.object_id = %s
        """, (obj_id,))
        attrs = cursor.fetchall()

        attr_dict = {}
        for attr in attrs:
            value = attr['string_value'] or attr['dict_value'] or attr['uint_value'] or attr['float_value']
            attr_dict[attr['attr_name']] = {
                "type": attr['attr_type'],
                "value": value
            }

        # Add explicit_tags to attr_dict
        attr_dict["explicit_tags"] = tags

        # -------------------------------
        # FILTER 4: By STATUS (Etat Equipement = "En Service")
        # -------------------------------
        etat_equipement = attr_dict.get("Etat Equipement", {}).get("value")
        if etat_equipement != "En Service":
            logger.info(f"❌ Object rejected (not in service): name={obj_name}, Etat Equipement={etat_equipement}")
            rejected_by_status += 1
            continue

        # -------------------------------
        # ✅ OBJECT ACCEPTED (passes all 4 filters)
        # -------------------------------
        logger.info(f"✅ Object accepted: name={obj_name}, role={role} (pattern: {pattern})")

        # -------------------------------
        # Initialize object in racktables_map
        # -------------------------------
        racktables_map[obj_id] = {
            "racktables_id": formatted_id,
            "name": obj_name,
            "label": obj_label,
            "type": obj_type,
            "role": role,
            "role_pattern": pattern,
            "attrs": attr_dict,
            "ipv4": [],
            "ipv6": [],
            "interfaces": [],
            "links": [],
            "rackspace": None
        }

        # -------------------------------
        # Rackspace info
        # -------------------------------
        cursor.execute("""
            SELECT r.name AS rack_name, rs.unit_no, rs.atom
            FROM RackSpace rs
            JOIN Rack r ON rs.rack_id = r.id
            WHERE rs.object_id = %s
        """, (obj_id,))
        rack_info = cursor.fetchone()
        if rack_info:
            display = f"{rack_info['atom']}{rack_info['unit_no']}:{rack_info['rack_name']}"
            racktables_map[obj_id]["rackspace"] = {
                "rack_name": rack_info['rack_name'],
                "unit": rack_info['unit_no'],
                "atom": rack_info['atom'],
                "display": display
            }


    # -------------------------------
    # Count retained objects
    # -------------------------------
    retained_count = len(racktables_map)
    total_rejected = rejected_by_tag + rejected_by_type + rejected_by_role + rejected_by_status
    logger.info(f"📊 Filtering summary:")
    logger.info(f"   ✅ {retained_count} objects retained")
    logger.info(f"   ❌ {rejected_by_tag} objects rejected (invalid Domain tags)")
    logger.info(f"   ❌ {rejected_by_type} objects rejected (invalid type)")
    logger.info(f"   ❌ {rejected_by_role} objects rejected (no role found)")
    logger.info(f"   ❌ {rejected_by_status} objects rejected (not in service)")
    logger.info(f"   📉 Total rejected: {total_rejected}")

    # -------------------------------
    # 4. IPv4 allocations
    # -------------------------------
    logger.info("Retrieving IPv4 allocations...")

    # Network list
    cursor.execute("SELECT ip, mask, name, comment FROM IPv4Network")
    network_list = cursor.fetchall()

    # Enriched IPv4 allocations (also retrieving interface name)
    cursor.execute("SELECT ip, object_id, type, name FROM IPv4Allocation")
    allocs = cursor.fetchall()

    ignored_ipv4 = 0

    for alloc in allocs:
        ip = alloc['ip']
        object_id = alloc['object_id']
        alloc_type = alloc['type']
        alloc_name = alloc.get('name')

        # Ignore objects without valid tags
        if object_id not in racktables_map:
            ignored_ipv4 += 1
            continue

        ip_str = int_to_ip(ip)
        network_cidr = None
        net_name = None
        net_comment = None

        # Find the network associated with this IP
        for net in network_list:
            start_ip = net['ip']
            end_ip = start_ip + (2 ** (32 - net['mask']) - 1)
            if start_ip <= ip <= end_ip:
                network_cidr = f"{int_to_ip(net['ip'])}/{net['mask']}"
                net_name = net['name']
                net_comment = net['comment']
                break

        # Add to the map
        racktables_map[object_id].setdefault("ipv4", []).append({
            "ip": ip_str,
            "type": alloc_type,
            "name": alloc_name,
            "network": {
                "cidr": network_cidr,
                "name": net_name,
                "comment": net_comment
            }
        })

    logger.info(f"✅ IPv4 allocations processed, {ignored_ipv4} entries ignored")

    # -------------------------------
    # 5. IPv6 allocations
    # -------------------------------
    import ipaddress

    logger.info("Retrieving IPv6 allocations...")

    # Retrieve IPv6 networks
    cursor.execute("SELECT ip, mask, name, comment FROM IPv6Network")
    ipv6_networks = cursor.fetchall()

    # Retrieve IPv6 allocations
    cursor.execute("SELECT ip, object_id, type, name FROM IPv6Allocation")
    ipv6_allocs = cursor.fetchall()

    ignored_ipv6 = 0

    for alloc in ipv6_allocs:
        ip_str = bin_to_ipv6(alloc.get('ip'))
        object_id = alloc.get('object_id')
        alloc_type = alloc.get('type')
        alloc_name = alloc.get('name')

        if not ip_str or object_id not in racktables_map:
            ignored_ipv6 += 1
            continue

        # Find parent network
        network_cidr = None
        net_name = None
        net_comment = None

        for net in ipv6_networks:
            net_ip_str = bin_to_ipv6(net.get('ip'))
            try:
                prefix = ipaddress.IPv6Network(f"{net_ip_str}/{net['mask']}", strict=False)
                if ipaddress.IPv6Address(ip_str) in prefix:
                    network_cidr = str(prefix)
                    net_name = net['name']
                    net_comment = net['comment']
                    break
            except Exception:
                continue

        # Add to the map
        racktables_map[object_id].setdefault("ipv6", []).append({
            "ip": ip_str,
            "type": alloc_type,
            "name": alloc_name,
            "network": {
                "cidr": network_cidr,
                "name": net_name,
                "comment": net_comment
            }
        })

    logger.info(f"✅ IPv6 allocations processed, {ignored_ipv6} entries ignored")


    # -------------------------------
    # 6. Interfaces (via SQL)
    # -------------------------------
    logger.info("Retrieving interfaces via SQL...")

    obj_ids = tuple(racktables_map.keys())
    if not obj_ids:
        logger.warning("⚠️ No objects with valid tags, no ports to retrieve")
    else:
        cursor.execute(f"""
            SELECT p.id          AS port_id,
                p.name        AS port_name,
                p.label       AS port_label,
                p.type        AS port_type,
                d.dict_value  AS port_type_name,
                o.id          AS object_id,
                o.name        AS device_name
            FROM Port p
            JOIN Object o ON p.object_id = o.id
            LEFT JOIN Dictionary d ON p.type = d.dict_key
            WHERE o.id IN ({','.join(['%s']*len(obj_ids))})
            ORDER BY o.id, p.name
        """, obj_ids)

        ports = cursor.fetchall()

        # Group by (object_id, port_name)
        grouped_ports = {}
        for port in ports:
            key = (port['object_id'], port['port_name'])
            grouped_ports.setdefault(key, []).append(port)

        # Create interface_data with virtual + physical
        for (obj_id, port_name), plist in grouped_ports.items():
            interface_data = {"if_name": port_name}

            for p in plist:
                pdata = {
                    "local_object_id": p["object_id"],
                    "local_device_name": p["device_name"],
                    "local_port_name": p["port_name"],
                    "local_port_label": p.get("port_label") or "",
                    "local_port_type_name": p["port_type_name"] or ("virtual port" if p["type"] == 1469 else "RJ45"),
                    "local_port_id": p["port_id"],
                    "local_port_type": p["port_type"]
                }
                if (p["port_type_name"] and "virtual" in p["port_type_name"].lower()) or p["port_type"] == 1469:
                    interface_data["virtual_port"] = pdata
                else:
                    interface_data["physical_port"] = pdata

            racktables_map[obj_id].setdefault("interfaces", []).append(interface_data)

    # Count number of interfaces
    total_interfaces = sum(len(d['interfaces']) for d in racktables_map.values())
    logger.info(f"📊 Total interfaces: {total_interfaces}")

    # -------------------------------
    # 7. Links (enriching interfaces)
    # -------------------------------
    logger.info("Retrieving links and enriching interfaces...")

    physical_links_count = 0
    virtual_links_count = 0

    for obj_id, obj_data in racktables_map.items():
        cursor.execute("""
            SELECT *
            FROM (
                SELECT
                    pa.id   AS port_id_a, pa.name AS port_name_a, pa.type AS port_type_a,
                    oa.id   AS object_id_a, oa.name AS device_name_a,
                    pb.id   AS port_id_b, pb.name AS port_name_b, pb.type AS port_type_b,
                    ob.id   AS object_id_b, ob.name AS device_name_b,
                    l.cable
                FROM Link l
                JOIN Port pa ON pa.id = l.porta
                JOIN Port pb ON pb.id = l.portb
                JOIN Object oa ON oa.id = pa.object_id
                JOIN Object ob ON ob.id = pb.object_id
                WHERE oa.id = %s

                UNION ALL

                SELECT
                    pb.id   AS port_id_a, pb.name AS port_name_a, pb.type AS port_type_a,
                    ob.id   AS object_id_a, ob.name AS device_name_a,
                    pa.id   AS port_id_b, pa.name AS port_name_b, pa.type AS port_type_b,
                    oa.id   AS object_id_b, oa.name AS device_name_b,
                    l.cable
                FROM Link l
                JOIN Port pa ON pa.id = l.porta
                JOIN Port pb ON pb.id = l.portb
                JOIN Object oa ON oa.id = pa.object_id
                JOIN Object ob ON ob.id = pb.object_id
                WHERE ob.id = %s
            ) AS links_sorted
            ORDER BY port_name_a
        """, (obj_id, obj_id))

        links = cursor.fetchall()

        # Enrich existing interfaces with link info
        for if_data in obj_data.get("interfaces", []):
            for port_kind in ["virtual_port", "physical_port"]:
                if port_kind in if_data:
                    local_port_id = if_data[port_kind]["local_port_id"]

                    # Find corresponding link
                    for link in links:
                        if link["port_id_a"] == local_port_id:
                            if_data[port_kind].update({
                                "remote_object_id": link["object_id_b"],
                                "remote_device_name": link["device_name_b"],
                                "remote_port_name": link["port_name_b"],
                                "remote_port_type_name": "virtual port" if port_kind=="virtual_port" else "RJ45",
                                "remote_port_id": link["port_id_b"],
                                "remote_port_type": link["port_type_b"],
                                "cable": link["cable"]
                            })
                            # Count by port type
                            if port_kind == "virtual_port":
                                virtual_links_count += 1
                            else:
                                physical_links_count += 1

    logger.info(f"📊 Links attached to interfaces: {physical_links_count} physical / {virtual_links_count} virtual")

    # -------------------------------
    # 8. Virtual/physical consistency check
    # -------------------------------
    logger.info("🔍 Checking interfaces: virtual/physical consistency...")

    for obj_id, obj_data in racktables_map.items():
        for if_data in obj_data.get("interfaces", []):
            virtual_port = if_data.get("virtual_port")
            physical_port = if_data.get("physical_port")

            # Case 1: virtual with remote but physical without remote
            if virtual_port and "remote_object_id" in virtual_port:
                if physical_port is None or "remote_object_id" not in physical_port:
                    logger.warning(
                        f"⚠️ Virtual port configured but physical remote missing for "
                        f'local_device_name="{virtual_port["local_device_name"]}", '
                        f'if_name="{if_data["if_name"]}"'
                    )

            # Case 2: physical with remote but virtual without remote
            if physical_port and "remote_object_id" in physical_port:
                if virtual_port is None or "remote_object_id" not in virtual_port:
                    logger.warning(
                        f"⚠️ Physical port configured but virtual remote missing for "
                        f'local_device_name="{physical_port["local_device_name"]}", '
                        f'if_name="{if_data["if_name"]}", '
                        f'cable id="{physical_port["cable"]}"'
                    )


    # -------------------------------
    # 9. Group by main tag
    # -------------------------------
    grouped = {"Nplus1": {}, "N": {}, "UNKNOWN": {}}

    for obj_id, obj_data in racktables_map.items():
        tags = obj_data["attrs"].get("explicit_tags", [])
        main_tag = None
        if "Nplus1" in tags:
            main_tag = "Nplus1"
        elif "N" in tags:
            main_tag = "N"
        else:
            main_tag = "UNKNOWN"

        for tag in tags:
            grouped.setdefault(main_tag, {}).setdefault(tag, []).append({
                "object_id": obj_id,
                "name": obj_data["name"],
                "label": obj_data["label"],
                "type": obj_data["type"],
                "role": obj_data["role"]
            })

    # -------------------------------
    # 10. Export "flat" JSON for NetBox
    # -------------------------------
    logger.info("📦 Generating flat JSON for NetBox...")

    flat_racktables_map = {}
    hw_type_normalization_log = []

    for obj_id, obj_data in racktables_map.items():
        flat_obj = {
            "racktables_id": obj_data["racktables_id"],
            "name": obj_data["name"],
            "label": obj_data["label"],
            "type": obj_data["type"],
            "role": obj_data["role"],
            "role_pattern": obj_data["role_pattern"],
            "ipv4": obj_data["ipv4"],
            "ipv6": obj_data["ipv6"],
            "interfaces": obj_data["interfaces"],
            "links": obj_data["links"],
            "rackspace": obj_data["rackspace"]
        }

        # Copy attributes flat (including explicit_tags)
        has_hw_type = False
        for attr_name, attr_info in obj_data["attrs"].items():
            key = attr_name.strip().replace(" ", "_").replace("-", "_")

            # If attr_info is a dict with a "value" key
            if isinstance(attr_info, dict) and "value" in attr_info:
                value = attr_info["value"]

                # Normalize HW type using mapping (also deduce from name if empty)
                if attr_name == "HW type":
                    has_hw_type = True
                    value = normalize_hw_type(
                        value,
                        DEVICES_TYPES_MAPPING,
                        YAML_DEVICE_TYPES,
                        device_name=obj_data["name"],
                        name_patterns=NAME_TO_HWTYPE_PATTERNS,
                        normalization_log=hw_type_normalization_log
                    )

                flat_obj[key] = value
            else:
                # Special case: explicit_tags (or other raw list)
                flat_obj[key] = attr_info

        # Ensure HW_type is always present (deduce from name if missing)
        if not has_hw_type:
            flat_obj["HW_type"] = normalize_hw_type(
                None,
                DEVICES_TYPES_MAPPING,
                YAML_DEVICE_TYPES,
                device_name=obj_data["name"],
                name_patterns=NAME_TO_HWTYPE_PATTERNS,
                normalization_log=hw_type_normalization_log
            )

        flat_racktables_map[obj_id] = flat_obj

    RacktablesExporter.export_json("racktables_map.json", racktables_map)
    RacktablesExporter.export_json("racktables_map_flat_netbox.json", flat_racktables_map)
    RacktablesExporter.export_json("racktables_object_names.json", {obj_id: data["name"] for obj_id, data in racktables_map.items()})
    RacktablesExporter.export_json("racktables_map_grouped_by_main_tag.json", grouped)

    # -------------------------------
    # 11. Export HW type normalization log
    # -------------------------------
    if hw_type_normalization_log:
        RacktablesExporter.export_json("hw_type_normalization_log.json", hw_type_normalization_log)

        # Log summary
        no_match = [e for e in hw_type_normalization_log if e["method"] == "no_hw_type_no_pattern"]
        deduced = [e for e in hw_type_normalization_log if "deduced_from_name" in e["method"]]
        normalized = [e for e in hw_type_normalization_log if e["method"] not in ["no_hw_type_no_pattern"] and "deduced_from_name" not in e["method"]]

        logger.info(f"📊 HW type normalization summary:")
        logger.info(f"   🔄 {len(normalized)} devices with HW type normalized")
        logger.info(f"   🔍 {len(deduced)} devices with HW type deduced from name")
        logger.info(f"   ⚠️  {len(no_match)} devices without HW type (no pattern match)")

        if no_match:
            logger.warning(f"⚠️  Devices without HW type:")
            for entry in no_match:
                logger.warning(f"      - {entry['device_name']}")

    filepath = Path(__file__).parent.parent / "common/data/raw/racktables-data.json"
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding='utf-8') as f:
        json.dump(flat_racktables_map, f, indent=4, ensure_ascii=False)


    # -------------------------------
    # Cleanup
    # -------------------------------
    if db:
        db.close()
        logger.info("✅ Database connection closed")

    logger.info("✅ Complete pipeline finished")
