import logging
import sys
import pynetbox
from json import dumps as json_dumps
from json import load as js_load
import requests
from yaml import dump as yl_dump
from time import sleep, time
from racktables.racktables_db_extract import gathering_racktables_data
import json
import copy
import yaml
from typing import Dict, List, Optional, Any
from sdk.polatis import Polatis
from pyats.utils.secret_strings import to_plaintext


class GetLogger:
    """Logger singleton pour l'application."""

    _logger = None

    @classmethod
    def init_log(cls, name: str = "NetBoxManager", level: int = logging.INFO) -> logging.Logger:
        """Initialize and return logger instance."""
        if cls._logger is None:
            cls._logger = logging.getLogger(name)
            cls._logger.setLevel(level)

            cls._logger.propagate = False

            # Console handler
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(level)

            # Formatter
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)

            cls._logger.addHandler(handler)

        return cls._logger

class CableNotCreated(Exception):
    pass

LOGGER = GetLogger.init_log()
class NetboxManager:
    """Manager for NetBox operations with create/update support."""

    def __init__(self, url: str, token: str):
        """
        Initialize NetBox API client.

        Args:
            url: NetBox URL
            token: API token
            proxy: Proxy URL (optional)
        """
        self.nb = pynetbox.api(url, token)
        session = requests.Session()
        session.trust_env = False  # Ignore http_proxy de l'environnement
        # if proxy:
        #     session.proxies = {"http": proxy, "https": proxy}
        self.nb.http_session = session

    def _compare_and_update(
        self,
        existing_obj,
        new_data: dict,
        excluded_keys: Optional[list] = None
    ) -> dict:
        """
        Compare existing object with new data and return differences.

        Args:
            existing_obj: Existing NetBox object
            new_data: New data to compare
            excluded_keys: Keys to exclude from comparison

        Returns:
            Dictionary of detected differences
        """
        if excluded_keys is None:
            excluded_keys = []

        diff = {}
        obj_dict = dict(existing_obj)

        for key, value in new_data.items():
            if key in excluded_keys:
                continue

            # Handle custom_fields
            if key == "custom_fields":
                if not isinstance(value, dict):
                    # custom_fields=None ou type inattendu → ignorer pour éviter
                    # TypeError: 'NoneType' object is not iterable dans _apply_update
                    continue
                for cf_key, cf_val in value.items():
                    existing_val = obj_dict.get(key, {}).get(cf_key, None)
                    if existing_val != cf_val:
                        diff.setdefault("custom_fields", {})[cf_key] = cf_val
            else:
                existing_val = obj_dict.get(key, None)

                # Handle dict objects with 'value' key
                if isinstance(existing_val, dict) and 'value' in existing_val:
                    existing_val = existing_val['value']

                # Handle NetBox objects (extract ID)
                if isinstance(existing_val, dict) and 'id' in existing_val:
                    existing_val = existing_val['id']

                logging.debug(f"Comparing field '{key}': existing='{existing_val}' vs new='{value}'")
                if existing_val != value:
                    diff[key] = value

        return diff

    def _apply_update(self, obj, diff: dict, description: str):
        """
        Apply updates to a NetBox object.

        Args:
            obj: NetBox object to update
            diff: Dictionary of changes
            description: Object name for logging

        Returns:
            Updated object or None on error
        """
        try:
            LOGGER.info(f"Updating {description} with changes:\n{json_dumps(diff, indent=2)}")
            for key, value in diff.items():
                if key == "custom_fields":
                    if not isinstance(value, dict):
                        LOGGER.warning(
                            f"Skipping custom_fields update for {description}: "
                            f"expected dict, got {type(value).__name__}"
                        )
                        continue
                    obj.custom_fields.update(value)
                else:
                    setattr(obj, key, value)
            obj.save()
            LOGGER.info(f"Successfully updated {description}")
            return obj
        except Exception as e:
            raise Exception(f"Failed to update {description}: {e}") from e

    def _prepare_device_data(self, data: dict, validate_required: bool = False) -> dict:
        """Prepare device data by resolving references to IDs."""
        data_copy = data.copy()

        # Handle platform
        platform_name = data.get('platform')
        if platform_name:
            platform = self.nb.dcim.platforms.get(name=platform_name)
            if not platform:
                LOGGER.info(f"Auto-creating platform '{platform_name}'")
                platform = self.nb.dcim.platforms.create({
                    "name": platform_name,
                    "slug": platform_name.lower().replace(' ', '-')
                })
            data_copy["platform"] = platform.id

        # Handle site
        site = self.nb.dcim.sites.get(name=data.get('site'))
        if validate_required and not site:
            raise ValueError(f"Site '{data.get('site')}' not found")
        if site:
            data_copy["site"] = site.id

        # Handle role
        slug = data.get('role')
        if not slug:
            if validate_required:
                raise ValueError(
                    f"Device '{data.get('name')}' has no role defined (role is null or missing in YAML)"
                )
        else:
            role = self.nb.dcim.device_roles.get(slug=slug)
            if validate_required and not role:
                raise ValueError(f"Device role '{slug}' not found in NetBox")
            if role:
                data_copy["role"] = role.id

        # Handle device_type
        dtype = self.nb.dcim.device_types.get(model=data.get('device_type'))
        if validate_required and not dtype:
            raise ValueError(f"Device type '{data.get('device_type')}' not found")
        if dtype:
            data_copy["device_type"] = dtype.id

        # Handle tenant
        tenant_name = data.get('tenant')
        if tenant_name:
            tenant = self.nb.tenancy.tenants.get(name=tenant_name)
            data_copy["tenant"] = tenant.id if tenant else None

        # Handle rack
        rack = self.get_rack(
            name=data.get('rack'),
            site=site
        )
        if rack:
            data_copy["rack"] = rack.id
        return data_copy

    def get_device(self, name: str):
        """Get device by name."""
        return self.nb.dcim.devices.get(name=name)

    def get_rack(self, name: str, site: str):
        rack = next(
            iter(self.nb.dcim.racks.filter(name=name, site=site)),
            None
        )
        return rack

    def _get_termination(self, termination_type: str, device_id: int, name: str):
        """
        Get termination object based on type.

        Args:
            termination_type: Type of termination (dcim.interface, dcim.consoleport, etc.)
            device_id: Device ID
            name: Termination name

        Returns:
            Termination object or None
        """
        type_mapping = {
            'dcim.interface': self.nb.dcim.interfaces,
            'dcim.consoleport': self.nb.dcim.console_ports,
            'dcim.consoleserverport': self.nb.dcim.console_server_ports,
            'dcim.frontport': self.nb.dcim.front_ports,
            'dcim.rearport': self.nb.dcim.rear_ports,
            'dcim.powerfeed': self.nb.dcim.power_feeds,
            'dcim.poweroutlet': self.nb.dcim.power_outlets,
            'dcim.powerport': self.nb.dcim.power_ports,
        }

        endpoint = type_mapping.get(termination_type.lower())
        if not endpoint:
            raise ValueError(f"Unknown termination type: {termination_type}")

        return next(iter(endpoint.filter(device_id=device_id, name=name)), None)

    def _compare_cable_data(self, existing_cable, new_data: dict) -> dict:
        """Compare existing cable with new data and return differences."""
        diff = {}
        cable_dict = dict(existing_cable)

        # Fields to compare
        comparable_fields = ['type', 'status', 'label', 'color', 'length', 'length_unit', 'description', 'tenant']

        for field in comparable_fields:
            if field not in new_data:
                continue

            new_val = new_data[field]
            existing_val = cable_dict.get(field)

            # Handle nested objects
            if hasattr(existing_val, 'id'):
                existing_val = existing_val.id
            if isinstance(existing_val, dict) and 'value' in existing_val:
                existing_val = existing_val['value']

            if existing_val != new_val:
                diff[field] = new_val

        # Compare terminations a and b
        for side in ['a_terminations', 'b_terminations']:
            if side not in new_data:
                continue

            new_terminations = new_data[side]  # [{"object_type": ..., "object_id": ...}]
            existing_terminations = cable_dict.get(side, [])  # [{"object_type": ..., "object_id": ..., "object": {...}}]

            # Normalize existing terminations to {object_type, object_id} only for comparison
            existing_normalized = [
                {
                    "object_type": t.get("object_type"),
                    "object_id": t.get("object_id"),
                }
                for t in existing_terminations
                if t.get("object_id") is not None  # Ignore lost terminations (deleted device)
            ]

            # Normalize new terminations for comparison
            new_normalized = [
                {
                    "object_type": t.get("object_type"),
                    "object_id": t.get("object_id"),
                }
                for t in new_terminations
            ]

            if existing_normalized != new_normalized:
                diff[side] = new_terminations

        return diff

    def get_rack(self, name: str, site: str):
        """Get rack by name and site.

        Args:
            name: Rack name
            site: Site name

        Returns:
            Rack object or None
        """
        site_obj = self.nb.dcim.sites.get(name=site)
        if not site_obj:
            LOGGER.warning(f"Site '{site}' not found")
            return None

        return next(
            iter(self.nb.dcim.racks.filter(name=name, site_id=site_obj.id)),
            None
        )

    def get_create_cable_from_interface_data(self, interface_data: dict):
        """
        Create cable automatically from interface custom_fields.
        Looks for 'remote_device' and 'remote_port_name' in custom_fields.

        Args:
            interface_data: Interface data dictionary containing custom_fields

        Returns:
            Cable object or None if remote info not found
        """
        custom_fields = interface_data.get('custom_fields', {})
        remote_device = custom_fields.get('remote_device')
        remote_port = custom_fields.get('remote_port_name')

        if not remote_device or not remote_port:
            raise CableNotCreated(f"No remote connection info for interface '{interface_data.get('name')}'")

        # Build cable data
        cable_data = {
            'a_device': interface_data.get('device'),
            'a_termination_name': interface_data.get('name'),
            'a_termination_type': 'dcim.interface',
            'b_device': remote_device,
            'b_termination_name': remote_port,
            'b_termination_type': 'dcim.interface',
            'label': interface_data.get('label'),
            'description': interface_data.get('description'),
            'status': 'connected' if not interface_data.get('mark_connected') else 'planned',
        }

        # Add cable type based on interface type
        interface_type = interface_data.get('type', '')
        if 'fiber' in interface_type.lower() or 'gbase' in interface_type.lower():
            cable_data['type'] = 'smf'  # Single-mode fiber by default

        return self.create_or_update_cable(cable_data)

    def close_netbox_session(self):
        """
        Properly closes the NetBox HTTP session if it exists.

        This method checks for the presence of the NetBox object and its HTTP session
        before attempting to close it, in order to avoid any unnecessary exceptions.
        """
        try:
            session = getattr(self.nb, "http_session", None)
            if session:
                session.close()
                LOGGER.info("Finished to close netbox session")
        except  Exception as e:
            LOGGER.error(f"Failed to close netbox session:{e}")

    def create_or_update_region(self, data: dict):
        """Create or update a NetBox region."""
        name = data.get("name")
        slug = data.get('slug')
        region = self.nb.dcim.regions.get(slug=slug)

        if region:
            LOGGER.info(f"Region '{region.name}' exists (ID: {region.id})")
            diff = self._compare_and_update(region, data, excluded_keys=["name"])
            if diff:
                return self._apply_update(region, diff, f"region '{region.name}'")
            return region

        LOGGER.info(f"Creating region '{name}'")
        try:
            return self.nb.dcim.regions.create(data)
        except Exception as e:
            raise Exception(f"Failed to create region '{name}' because: {e}")

    def create_or_update_tenant(self, data: dict):
        """Create or update a NetBox tenant."""
        name = data.get("name")
        slug = data.get("slug")
        tenant = self.nb.tenancy.tenants.get(slug=slug)

        if tenant:
            LOGGER.info(f"Tenant '{tenant.name}' exists (ID: {tenant.id})")
            diff = self._compare_and_update(tenant, data, excluded_keys=["name"])
            if diff:
                return self._apply_update(tenant, diff, f"tenant '{tenant.name}'")
            return tenant

        LOGGER.info(f"Creating tenant '{name}'")
        try:
            return self.nb.tenancy.tenants.create(data)
        except Exception as e:
            raise Exception(f"Failed to create tenant '{name}' because: {e}")

    def create_or_update_site_group(self, data: dict) -> Any:
        """Create or update a site group.

        Args:
            data: Site group data dictionary containing:
                - name: Site group name
                - slug: URL-friendly slug
                - parent: Parent site group slug (optional)
                - description: Description (optional)

        Returns:
            Site group object
        """
        name = data.get('name')
        slug = data.get('slug')
        site_group = self.nb.dcim.site_groups.get(slug=slug)

        parent_slug = data.get('parent')
        if parent_slug:
            parent_group = self.nb.dcim.site_groups.get(slug=parent_slug)
            if parent_group:
                data["parent"] = parent_group.id
            else:
                raise Exception(
                    f"Parent site group '{parent_slug}' not found. "
                    "Creating site group without parent."
                )

        if site_group:
            LOGGER.info(f"Site group '{name}' exists (ID: {site_group.id})")
            diff = self._compare_and_update(
                site_group,
                data,
                excluded_keys=['name', 'slug']
            )
            if diff:
                return self._apply_update(site_group, diff, f"site group '{name}'")
            return site_group

        LOGGER.info(f"Creating site group '{name}'")
        return self.nb.dcim.site_groups.create(data)

    def create_or_update_site(self, data: dict):
        """Create or update a site."""
        name = data.get('name')
        site = self.nb.dcim.sites.get(name=name)
        tenant_slug = data.get("tenant")

        LOGGER.info(f"Creating site '{name}'")
        group_slug = data.get('group')
        if isinstance(group_slug, str):
            site_group = self.nb.dcim.site_groups.get(slug=group_slug)
            if site_group:
                data["group"] = site_group.id
            else:
                raise Exception(f"Site group '{group_slug}' not found. The site group must exist in Netbox before creating site")

        region_slug = data.get("region")
        if isinstance(region_slug, str):
            region = self.nb.dcim.regions.get(slug=region_slug)
            if not region:
                raise Exception(f"Region '{region_slug}' not found. The region '{region_slug}' must exist in Netbox before creating site")
            data["region"] = region.id

        if isinstance(tenant_slug, str):
            tenant = self.nb.tenancy.tenants.get(slug=tenant_slug)
            if not tenant:
                raise Exception(f"Tenant '{tenant_slug}' not found. The tenant '{tenant_slug}' must exist in Netbox before creating site")
            data["tenant"] = tenant.id

        if site:
            LOGGER.info(f"Site '{name}' exists (ID: {site.id})")
            diff = self._compare_and_update(site, data, excluded_keys=['name'])
            if diff:
                return self._apply_update(site, diff, f"site '{name}'")
            return site

        try:
            return self.nb.dcim.sites.create(data)
        except Exception as e:
            raise Exception(f"Failed to create site  '{name}' because: {e}")

    def create_or_update_device_role(self, data: dict):
        """Create or update a device role."""
        name = data.get('name')
        slug = data.get('slug')
        parent_name = data.get('parent', '')
        if parent_name:
            parent = self.nb.dcim.device_roles.get(slug=parent_name)
            if not parent:
                LOGGER.warning(f"Parent device role '{parent_name}' not found, creating '{name}' without parent")
                data.pop('parent', None)
            else:
                data['parent'] = parent.id

        role = self.nb.dcim.device_roles.get(slug=slug)

        if role:
            LOGGER.info(f"Device role '{name}' exists (ID: {role.id})")
            diff = self._compare_and_update(role, data, excluded_keys=['name'])
            if diff:
                return self._apply_update(role, diff, f"role '{name}'")
            return role

        LOGGER.info(f"Creating device role '{name}'")
        try:
            return self.nb.dcim.device_roles.create(data)
        except Exception as e:
            raise Exception(f"Failed to create device role '{name}' because: {e}")

    def create_or_update_manufacturer(self, data: dict):
        """Create or update a manufacturer."""
        name = data.get('name')
        manufacturer = self.nb.dcim.manufacturers.get(name=name)

        if manufacturer:
            LOGGER.info(f"Manufacturer '{name}' exists (ID: {manufacturer.id})")
            diff = self._compare_and_update(manufacturer, data, excluded_keys=['name'])
            if diff:
                return self._apply_update(manufacturer, diff, f"manufacturer '{name}'")
            return manufacturer

        LOGGER.info(f"Creating manufacturer '{name}'")
        try:
            return self.nb.dcim.manufacturers.create(data)
        except Exception as e:
            raise Exception(f"Failed to create manufacturer '{name}' because: {e}")

    # def create_or_update_device_type(self, data: dict, device_type_path: str):
    #     """Create or update a device type."""
    #     manufacturer_name = data.get('manufacturer')
    #     manufacturer = self.nb.dcim.manufacturers.get(name=manufacturer_name)

    #     if not manufacturer:
    #         LOGGER.info(f"Auto-creating manufacturer '{manufacturer_name}'")
    #         manufacturer = self.nb.dcim.manufacturers.create({
    #             "name": manufacturer_name,
    #             "slug": manufacturer_name.lower().replace(' ', '-')
    #         })

    #     model = data.get('model')
    #     device_type = self.nb.dcim.device_types.get(model=model)

    #     # Extract the module bays from the data
    #     module_bays_data = data.pop('module-bays', [])
    #     if device_type:
    #         LOGGER.info(f"Device type '{model}' exists (ID: {device_type.id})")

    #         data_copy = data.copy()
    #         data_copy["manufacturer"] = manufacturer.id

    #         diff = self._compare_and_update(
    #             device_type,
    #             data_copy,
    #             excluded_keys=['model']
    #         )
    #         if diff:
    #             return self._apply_update(device_type, diff, f"device type '{model}'")

    #         LOGGER.info(f"Updated module-bays for device type: {model}")
    #         for mb in module_bays_data:
    #             mb["device_type"] = device_type.id
    #             print(type(mb))
    #             print(mb)
    #             self.nb.dcim.module_bay_templates.update(mb)
    #         return device_type

    #     try:
    #         data.update({"manufacturer": manufacturer.id})
    #         LOGGER.info(f"Creating device type '{model}'")
    #         device_type = self.nb.dcim.device_types.create(data)

    #         LOGGER.info(f"Creating device type components")
    #         self.create_device_type_components(device_type, data)
    #     except Exception as e:
    #         raise Exception(f"Failed to created device type and components: {device_type_path} because: {e}")

    def create_device_type_components(self, device_type, data):
        # Interfaces
        for iface in data.get("interfaces", []):
            iface["device_type"] = device_type.id
            self.nb.dcim.interface_templates.create(iface)

        # Console ports
        for cp in data.get("console-ports", []):
            cp["device_type"] = device_type.id
            self.nb.dcim.console_port_templates.create(cp)

        # Console server ports
        for csp in data.get("console-server-ports", []):
            csp["device_type"] = device_type.id
            self.nb.dcim.console_server_port_templates.create(csp)

        # Power ports
        for pp in data.get("power-ports", []):
            pp["device_type"] = device_type.id
            self.nb.dcim.power_port_templates.create(pp)

        # Power outlets
        for po in data.get("power-outlets", []):
            po["device_type"] = device_type.id
            self.nb.dcim.power_outlet_templates.create(po)

        # Rear ports
        for rp in data.get("rear-ports", []):
            rp["device_type"] = device_type.id
            self.nb.dcim.rear_port_templates.create(rp)

        # Front ports
        for fp in data.get("front-ports", []):
            fp["device_type"] = device_type.id
            self.nb.dcim.front_port_templates.create(fp)

        # Device bays
        for db in data.get("device-bays", []):
            db["device_type"] = device_type.id
            self.nb.dcim.device_bay_templates.create(db)

        # Module bays
        for mb in data.get("module-bays", []):
            mb["device_type"] = device_type.id
            self.nb.dcim.module_bay_templates.create(mb)

    # def create_or_update_device(self, data: dict):
    #     """Create or update a device."""
    #     device_name = data.get('name')
    #     device = self.nb.dcim.devices.get(name=device_name)
    #     device_type_path = data.get('device_type_path')

    #     if device_type_path:
    #         data.pop("device_type_path")

    #     from utils.functions import load_data_from_file
    #     if device:
    #         LOGGER.info(f"Device '{device_name}' exists (ID: {device.id})")
    #         try:
    #             # TODO
    #             device_type_data = load_data_from_file(
    #                 file_path=device_type_path,
    #                 file_extension="yaml"
    #             )
    #             self.create_or_update_device_type(
    #                 data=device_type_data,
    #                 device_type_path=device_type_path
    #             )

    #             # Prepare data with IDs
    #             data_copy = self._prepare_device_data(data)
    #             diff = self._compare_and_update(
    #                 device, data_copy, excluded_keys=['name', 'device_type']
    #             )

    #             if diff:
    #                 return self._apply_update(device, diff, f"device '{device_name}'")
    #             return device
    #         except Exception as e:
    #             raise Exception(
    #                 f"Failed to update device '{device_name}': {e}"
    #             ) from e

    #     try:
    #         device_type_data = load_data_from_file(
    #             file_path=device_type_path,
    #             file_extension="yaml"
    #         )
    #         self.create_or_update_device_type(data=device_type_data, device_type_path=device_type_path)
    #     except Exception as e:
    #         raise Exception(f"Failed to created device type components: {device_name} because: {e}")

    #     try:
    #         # Create new device
    #         data_prepared = self._prepare_device_data(data, validate_required=True)
    #         LOGGER.info(f"Creating device '{device_name}'")
    #         return self.nb.dcim.devices.create(data_prepared)
    #     except Exception as e:
    #         raise Exception(
    #             f"Failed to created device: {device_name} because: {e}"
    #         ) from e

    ################################################################################################################################################################################
    def create_or_update_device(self, data: dict):
        """Create or update a device."""
        device_name = data.get('name')
        device = self.nb.dcim.devices.get(name=device_name)
        device_type_path = data.get('device_type_path')

        if device_type_path:
            data.pop("device_type_path")

        if device:
            LOGGER.info(f"Device '{device_name}' exists (ID: {device.id})")
            try:
                # Vérifier et mettre à jour le device type si nécessaire
                if device_type_path:
                    from utils.functions import load_data_from_file
                    device_type_data = load_data_from_file(
                        file_path=device_type_path,
                        file_extension="yaml"
                    )
                    self.create_or_update_device_type(
                        data=device_type_data,
                        device_type_path=device_type_path
                    )

                # Préparer et mettre à jour le device
                data_copy = self._prepare_device_data(data)
                diff = self._compare_and_update(
                    device,
                    data_copy,
                    excluded_keys=['name']
                )

                if diff:
                    return self._apply_update(device, diff, f"device '{device_name}'")
                return device

            except Exception as e:
                raise Exception(
                    f"Failed to update device '{device_name}': {e}"
                ) from e

        # Créer le device type avant de créer le device
        if device_type_path:
            try:
                from utils.functions import load_data_from_file
                device_type_data = load_data_from_file(
                    file_path=device_type_path,
                    file_extension="yaml"
                )
                self.create_or_update_device_type(
                    data=device_type_data,
                    device_type_path=device_type_path
                )
            except Exception as e:
                raise Exception(
                    f"Failed to create device type components for '{device_name}': {e}"
                ) from e

        try:
            # Créer le nouveau device
            data_prepared = self._prepare_device_data(data, validate_required=True)
            LOGGER.info(f"Creating device '{device_name}'")
            return self.nb.dcim.devices.create(data_prepared)
        except Exception as e:
            raise Exception(
                f"Failed to create device '{device_name}': {e}"
            ) from e


    def create_or_update_device_type(self, data: dict, device_type_path: str):
        """Create or update a device type."""
        manufacturer_name = data.get('manufacturer')
        manufacturer = self.nb.dcim.manufacturers.get(name=manufacturer_name)

        if not manufacturer:
            LOGGER.info(f"Auto-creating manufacturer '{manufacturer_name}'")
            manufacturer = self.nb.dcim.manufacturers.create({
                "name": manufacturer_name,
                "slug": manufacturer_name.lower().replace(' ', '-')
            })

        model = data.get('model')
        device_type = self.nb.dcim.device_types.get(model=model)

        # Extract the module bays from the data
        module_bays_data = data.pop('module-bays', [])

        if device_type:
            LOGGER.info(f"Device type '{model}' exists (ID: {device_type.id})")

            data_copy = data.copy()
            data_copy["manufacturer"] = manufacturer.id

            diff = self._compare_and_update(
                device_type,
                data_copy,
                excluded_keys=['model']
            )

            if diff:
                device_type = self._apply_update(device_type, diff, f"device type '{model}'")

            # Update or recreate the module bay templates
            if module_bays_data:
                self._update_or_recreate_module_bay_templates(device_type, module_bays_data)

                # # If the templates have changed, propagate to existing devices
                # if templates_updated:
                LOGGER.info(f"Propagating module bay changes to existing devices using type '{model}'")
                self._sync_device_module_bays_from_templates(device_type, module_bays_data)

            return device_type

        # Create a new device type
        try:
            data["manufacturer"] = manufacturer.id
            # u_height is required by NetBox and may not be null
            if data.get('u_height') is None:
                LOGGER.warning(
                    f"Device type '{model}' has no u_height defined, defaulting to 1"
                )
                data['u_height'] = 1
            LOGGER.info(f"Creating device type '{model}'")
            device_type = self.nb.dcim.device_types.create(data)

            # Créer les module bay templates
            if module_bays_data:
                LOGGER.info(f"Creating module bay templates for device type '{model}'")
                self._create_module_bay_templates(device_type, module_bays_data)

            return device_type

        except Exception as e:
            raise Exception(f"Failed to create device type '{device_type_path}': {e}") from e

    def _sync_device_module_bays_from_templates(self, device_type, module_bays_data: list):
        """Synchronize module bays on all devices using this device type with the updated templates."""
        try:
            # Récupérer tous les devices utilisant ce device type
            devices = list(self.nb.dcim.devices.filter(device_type_id=device_type.id))

            if not devices:
                LOGGER.info(f"No devices found using device type '{device_type.model}'")
                return

            LOGGER.info(f"Found {len(devices)} device(s) using device type '{device_type.model}'")

            for device in devices:
                try:
                    LOGGER.info(f"Synchronizing module bays for device '{device.name}'")

                    # Récupérer les module bays existants du device
                    existing_bays = list(self.nb.dcim.module_bays.filter(device_id=device.id))
                    existing_bays_dict = {bay.name: bay for bay in existing_bays}
                    expected_bays_dict = {bay['name']: bay for bay in module_bays_data}

                    existing_names = set(existing_bays_dict.keys())
                    expected_names = set(expected_bays_dict.keys())

                    # Mettre à jour ou créer les module bays
                    for bay_name, bay_data in expected_bays_dict.items():
                        if bay_name in existing_bays_dict:
                            # Mettre à jour si nécessaire
                            existing_bay = existing_bays_dict[bay_name]
                            updates = {}

                            new_label = bay_data.get('label')
                            if new_label is not None and existing_bay.label != new_label:
                                updates['label'] = new_label

                            # new_position = bay_data.get('position')
                            # if new_position is not None and existing_bay.position != new_position:
                            #     updates['position'] = new_position

                            if updates:
                                LOGGER.debug(f"Updating module bay '{bay_name}' on device '{device.name}'")
                                self._apply_update(existing_bay, updates, f"module bay '{bay_name}' on device '{device.name}'")
                        else:
                            # Créer un nouveau module bay
                            LOGGER.debug(f"Creating module bay '{bay_name}' on device '{device.name}'")
                            self.nb.dcim.module_bays.create({
                                'device': device.id,
                                'name': bay_name,
                                'label': bay_data.get('label'),
                                'position': bay_data.get('position')
                            })

                    # Supprimer les module bays obsolètes
                    for bay_name in existing_names - expected_names:
                        LOGGER.debug(f"Deleting obsolete module bay '{bay_name}' on device '{device.name}'")
                        existing_bays_dict[bay_name].delete()

                    LOGGER.info(f"Successfully synchronized module bays for device '{device.name}'")

                except Exception as e:
                    LOGGER.error(f"Failed to sync module bays for device '{device.name}': {e}")
                    # Continue avec les autres devices
                    continue

            LOGGER.info(f"Completed module bay synchronization for all devices")

        except Exception as e:
            raise Exception(f"Failed to sync device module bays from templates: {e}") from e


    def _update_or_recreate_module_bay_templates(self, device_type, module_bays_data: list):
        """Update existing module bay templates or recreate if structure changed."""
        try:
            # Retrieve existing module bay templates
            existing_templates = list(self.nb.dcim.module_bay_templates.filter(device_type_id=device_type.id))
            existing_templates_dict = {template.name: template for template in existing_templates}
            expected_templates_dict = {template['name']: template for template in module_bays_data}

            # Check if an incremental update is possible
            existing_names = set(existing_templates_dict.keys())
            expected_names = set(expected_templates_dict.keys())

            has_changes = False
            # If the names are identical, we can update
            if existing_names == expected_names:
                LOGGER.debug(f"Updating {len(module_bays_data)} module bay templates")

                for template_name, template_data in expected_templates_dict.items():
                    existing_template = existing_templates_dict[template_name]
                    updates = {}

                    new_label = template_data.get('label')
                    if new_label is not None and existing_template.label != new_label:
                        updates['label'] = new_label

                    # new_position = template_data.get('position')
                    # if new_position is not None and existing_template.position != new_position:
                    #     updates['position'] = new_position

                    if updates:
                        has_changes = True
                        LOGGER.debug(f"Updating module bay template '{template_name}': {updates}")
                        self._apply_update(existing_template, updates, f"module bay template '{template_name}'")

                if has_changes:
                    LOGGER.info("Successfully updated module bay templates")
                else:
                    LOGGER.info("All module bay templates are already up to date")
            else:
                has_changes = True
                # Different structure: delete and recreate
                LOGGER.info(f"Module bay structure changed - recreating all templates")
                LOGGER.info(f"Removed: {sorted(existing_names - expected_names)}")
                LOGGER.info(f"Added: {sorted(expected_names - existing_names)}")

                # Delete all old ones
                if existing_templates:
                    LOGGER.info(f"Deleting {len(existing_templates)} existing module bay templates")
                    for template in existing_templates:
                        LOGGER.debug(f"Deleting module bay template '{template.name}'")
                        template.delete()

                # Créer les nouveaux
                LOGGER.info(f"Creating {len(module_bays_data)} new module bay templates")
                for template_data in module_bays_data:
                    LOGGER.debug(f"Creating module bay template '{template_data.get('name')}'")
                    self.nb.dcim.module_bay_templates.create({
                        'device_type': device_type.id,
                        'name': template_data.get('name'),
                        'label': template_data.get('label'),
                        'position': template_data.get('position')
                    })

                LOGGER.info(f"Successfully recreated module bay templates")
            return has_changes
        except Exception as e:
            raise Exception(f"Failed to update/recreate module bay templates: {e}") from e


    def _create_module_bay_templates(self, device_type, module_bays_data: list):
        """Create module bay templates for a new device type."""
        try:
            for template_data in module_bays_data:
                LOGGER.debug(f"Creating module bay template '{template_data.get('name')}'")
                self.nb.dcim.module_bay_templates.create({
                    'device_type': device_type.id,
                    'name': template_data.get('name'),
                    'label': template_data.get('label'),
                    'position': template_data.get('position')
                })
            LOGGER.info(f"Successfully created {len(module_bays_data)} module bay templates")
        except Exception as e:
            raise Exception(f"Failed to create module bay templates: {e}") from e


    ################################################################################################################################################################################
    def create_or_update_custom_fields(self, data: dict):
        """
        Ensure that all custom fields required for NetBox exists.
        """
        if not data:
            return

        data_copy = data.copy()
        name = data.get("name")
        existing_cf = self.nb.extras.custom_fields.get(name=name)
        if existing_cf:
            LOGGER.info(f"Custom field '{name}' already exists (ID: {existing_cf.id})")
            diff = self._compare_and_update(existing_cf, data_copy, excluded_keys=['object_types'])
            if diff:
                return self._apply_update(existing_cf, diff, f"interface '{name}'")
            return name

        payload = {
            "name": name,
            "label": data.get("label"),
            "type": data.get("type", "text"),
            "object_types": data.get("object_types")
        }

        LOGGER.info(f"Creating custom field '{name}'")
        try:
            self.nb.extras.custom_fields.create(payload)
        except Exception as e:
            raise Exception(f"Failed to create custom field '{name}': {e}")


    def create_or_update_interface(self, data: dict):
        """Create or update an interface."""
        intf_name = data.get('name')
        device_name = data.get('device')

        # Get device
        device = self.nb.dcim.devices.get(name=device_name)
        if device is None or isinstance(device, pynetbox.core.response.RecordSet):

            devices = list(self.nb.dcim.devices.filter(name=device_name))
            if not devices:
                raise ValueError(f"Device '{device_name}' not found")

            device = devices[0]

        data_copy = data.copy()
        data_copy["device"] = device.id

        # Check if LAG exists
        if data_copy.get('lag'):
            lag_name = data_copy.get('lag')
            lag = next(
                iter(self.nb.dcim.interfaces.filter(device_id=device.id, name=lag_name)),
                None
            )
            if not lag:
                LOGGER.info(f"LAG '{lag_name}' doesn't exist on netbox.")
                raise Exception(f"Skipped to create interface '{intf_name}' with '{lag_name}'")
            data_copy['lag'] = lag.id

        # handle module
        if data_copy.get('module'):
            module_name = data_copy["module"]
            # module = next(
            #     iter(
            #         self.nb.dcim.modules.filter(
            #             device_id=device.id,
            #             module_bay__name=module_name
            #         )
            #     ),
            #     None
            # )

            module = next(
                (
                    m for m in self.nb.dcim.modules.filter(device_id=device.id)
                    if m['module_bay']['name'] == module_name
                ),
                None
            )
            data_copy["module"] = module.id

        # NetBox rejette custom_fields=None avec 400 Bad Request.
        # On normalise à {} si absent ou None, pour éviter cette erreur.
        if data_copy.get('custom_fields') is None:
            data_copy.pop('custom_fields', None)

        try:
            # Check if interface exists
            iface = next(
                iter(self.nb.dcim.interfaces.filter(device_id=device.id, name=intf_name)),
                None
            )

            if iface:
                LOGGER.info(f"Interface '{intf_name}' exists on '{device_name}'")
                diff = self._compare_and_update(iface, data_copy, excluded_keys=['device', 'name', 'enable'])
                if diff:
                    return self._apply_update(iface, diff, f"interface '{intf_name}'")
                return iface

            LOGGER.info(f"Creating interface '{intf_name}' on '{device_name}'")
            return self.nb.dcim.interfaces.create(data_copy)
        except Exception as e:
            raise Exception(
                f"Failed to create/update interface '{intf_name}' on '{device_name}' {e}"
            )

    def create_or_update_ip_address(self, data: dict):
        """Create or update an IP address and attach it to an interface."""
        address = data.get('address')
        ip_address = self.nb.ipam.ip_addresses.get(address=address)

        # Prepare data for comparison/creation
        data_copy = data.copy()
        interface_name = data.get('interface')
        device_name = data.get('device')

        device = self.nb.dcim.devices.get(name=device_name)
        if not device:
            raise ValueError(f"Device '{device_name}' not found")

        interface = next(
            iter(self.nb.dcim.interfaces.filter(device_id=device.id, name=interface_name)),
            None
        )
        if not interface:
            raise ValueError(f"Interface '{interface_name}' not found on device '{device_name}' in NetBox")

        # Use assigned_object_type and assigned_object_id for NetBox 3.x+
        data_copy["assigned_object_type"] = "dcim.interface"
        data_copy["assigned_object_id"] = interface.id
        # Remove device from data (not direct fields)
        data_copy.pop('interface', None)
        data_copy.pop('device', None)

        if data.get('vrf'):
            vrf = self.nb.ipam.vrfs.get(name=data.get('vrf'))
            if vrf:
                data_copy["vrf"] = vrf.id
            else:
                LOGGER.warning(f"VRF '{data.get('vrf')}' not found, creating IP without VRF")
                data_copy.pop('vrf', None)

        if data.get('tenant'):
            tenant = self.nb.tenancy.tenants.get(slug=data.get('tenant'))
            if tenant:
                data_copy["tenant"] = tenant.id
            else:
                LOGGER.warning(f"Tenant '{data.get('tenant')}' not found, creating IP without tenant")
                data_copy.pop('tenant', None)

        if ip_address:
            LOGGER.info(f"IP address '{address}' exists (ID: {ip_address.id})")
            diff = self._compare_and_update(
                ip_address,
                data_copy,
                excluded_keys=['address']
            )
            if diff:
                return self._apply_update(ip_address, diff, f"IP address '{address}'")
            return ip_address

        try:
            LOGGER.info(f"Creating IP address '{address}'")
            return self.nb.ipam.ip_addresses.create(data_copy)
        except Exception as e:
            raise Exception(
                f"Failed to create  IP address '{address}' on interface: '{interface_name}' through device: '{device_name}': {e}"
            )

    def create_or_update_console_port(self, data: dict):
        """Create or update a console port on a device."""
        port_name = data.get('name')
        device_name = data.get('device')

        # Get device
        device = self.nb.dcim.devices.get(name=device_name)
        if device is None or isinstance(device, pynetbox.core.response.RecordSet):
            devices = list(self.nb.dcim.devices.filter(name=device_name))
            if not devices:
                raise ValueError(f"Device '{device_name}' not found")
            device = devices[0]

        data_copy = data.copy()
        data_copy["device"] = device.id

        # Check if console port exists
        console_port = next(
            iter(self.nb.dcim.console_ports.filter(device_id=device.id, name=port_name)),
            None
        )

        if console_port:
            LOGGER.info(f"Console port '{port_name}' exists on device '{device_name}'")
            diff = self._compare_and_update(
                console_port,
                data_copy,
                excluded_keys=['device', 'name']
            )
            if diff:
                return self._apply_update(console_port, diff, f"console port '{port_name}'")
            return console_port

        try:
            LOGGER.info(f"Creating console port '{port_name}' on device '{device_name}'")
            return self.nb.dcim.console_ports.create(data_copy)
        except Exception as e:
            raise Exception(
                f"Failed to create console port '{port_name}' on device '{device_name}' because: {e}"
            )

    def create_cables_from_interfaces(self, data: dict):
        # After creating the interfaces, automatically create the cables.
        cable_count = 0
        interface_dict = data
        custom_fields = interface_dict.get('custom_fields', {})

        if custom_fields.get('remote_device') and custom_fields.get('remote_port_name'):
            # Create a unique key to avoid creating the same cable twice
            device_a = interface_dict.get('device')
            port_a = interface_dict.get('name')
            device_b = custom_fields.get('remote_device')
            port_b = custom_fields.get('remote_port_name')

            LOGGER.info(f"\n{'='*60}")
            LOGGER.info(f"Auto-creating cables from {device_a}:{port_a}...")
            LOGGER.info(f"{'='*60}")

            try:
                cable = self.get_create_cable_from_interface_data(interface_dict)
                if cable:
                    cable_count += 1
                    LOGGER.info(
                        f"✓ Cable created: {device_a}:{port_a} <-> {device_b}:{port_b}"
                    )
                return cable
            except CableNotCreated as e:
                LOGGER.info(f"Cable creation skipped — {e}")
                return True
            except Exception as e:
                LOGGER.error(
                    f"Could not create cable {device_a}:{port_a} <-> {device_b}:{port_b}: {e}"
                )
                return None
        else:
            LOGGER.info(f"Cable is not created because no custom fields is defined.")
            return True

    def create_or_update_cable(self, data: dict):
        """
        Create or update a cable connection between two terminations (interfaces, console ports, etc.).

        Args:
            data: Dictionary containing:
                - a_termination_type: str (required) - Type of A-side (dcim.interface, dcim.consoleport, etc.)
                - a_device: str (required) - A-side device name
                - a_termination_name: str (required) - A-side port/interface name
                - b_termination_type: str (required) - Type of B-side
                - b_device: str (required) - B-side device name
                - b_termination_name: str (required) - B-side port/interface name
                - type: str (optional) - Cable type (cat3, cat5, cat5e, cat6, cat6a, cat7, cat7a, cat8, dac-active,
                    dac-passive, mrj21-trunk, coaxial, mmf, mmf-om1, mmf-om2, mmf-om3, mmf-om4, mmf-om5, smf, smf-os1, smf-os2, aoc, power)
                - status: str (optional) - Cable status (connected, planned, decommissioning)
                - label: str (optional) - Cable label
                - color: str (optional) - Cable color (hex format)
                - length: float (optional) - Cable length
                - length_unit: str (optional) - Length unit (km, m, cm, mi, ft, in)
                - description: str (optional) - Description
                - tenant: str (optional) - Tenant name

        Returns:
            Cable object or None on error
        """
        # Validate required fields
        required_fields = ['a_device', 'a_termination_name', 'b_device', 'b_termination_name']
        for field in required_fields:
            if not data.get(field):
                raise CableNotCreated(f"Missing required field: {field}")

        # Default termination types
        a_term_type = data.get('a_termination_type', 'dcim.interface')
        b_term_type = data.get('b_termination_type', 'dcim.interface')

        # Get A-side termination
        a_device = self.nb.dcim.devices.get(name=data.get('a_device'))
        if not a_device:
            raise CableNotCreated(
                f"the device '{data.get('a_device')}' does not exist in Netbox. Please verify the device name or create it first."
            )

        a_termination = self._get_termination(
            a_term_type,
            a_device.id,
            data.get('a_termination_name')
        )
        if not a_termination:
            raise CableNotCreated(
                f"the Termination '{data.get('a_termination_name')}' was not found on device '{data.get('a_device')}'"
            )

        # Get B-side termination
        b_device = self.nb.dcim.devices.get(name=data.get('b_device'))
        if not b_device:
            raise CableNotCreated(
                f"Device '{data.get('b_device')}' does not exist in Netbox. Please verify the device name or create it first."
            )

        b_termination = self._get_termination(
            b_term_type,
            b_device.id,
            data.get('b_termination_name')
        )
        if not b_termination:
            raise CableNotCreated(
                f"the Termination '{data.get('b_termination_name')}' was not found on device '{data.get('b_device')}'"
            )

        # Check if cable already exists on either termination
        existing_cable = None
        if hasattr(a_termination, 'cable') and a_termination.cable:
            existing_cable = self.nb.dcim.cables.get(a_termination.cable.id)
        elif hasattr(b_termination, 'cable') and b_termination.cable:
            existing_cable = self.nb.dcim.cables.get(b_termination.cable.id)

        # Prepare cable data
        data_copy = {
            "a_terminations": [{
                "object_type": a_term_type,
                "object_id": a_termination.id
            }],
            "b_terminations": [{
                "object_type": b_term_type,
                "object_id": b_termination.id
            }],
            "type": data.get('type'),
            "status": data.get('status', 'connected'),
            "label": data.get('label'),
            "color": data.get('color'),
            "length": data.get('length'),
            "length_unit": data.get('length_unit'),
            "description": data.get('description'),
        }

        # Resolve tenant if provided
        if data.get('tenant'):
            tenant = self.nb.tenancy.tenants.get(name=data.get('tenant'))
            if tenant:
                data_copy["tenant"] = tenant.id

        # Remove None values
        data_copy = {k: v for k, v in data_copy.items() if v is not None}

        if existing_cable:
            cable_label = data.get('label') or f"{data.get('a_device')}-{data.get('b_device')}"
            LOGGER.info(f"Cable exists (ID: {existing_cable.id}) for connection '{cable_label}'")

            # Compare and update if needed
            diff = self._compare_cable_data(existing_cable, data_copy)
            if diff:
                return self._apply_update(existing_cable, diff, f"cable '{cable_label}'")
            return existing_cable

        try:
            cable_label = data.get('label') or f"{data.get('a_device')}-{data.get('b_device')}"
            LOGGER.info(f"Creating cable connection '{cable_label}'")
            return self.nb.dcim.cables.create(data_copy)
        except Exception as e:
            raise Exception(
                f"Failed to create cable connection '{cable_label}' because: {e}"
            )

    def create_or_update_rack(self, data: dict):
        """Create or update a rack.

        Args:
            data: Rack data dictionary

        Returns:
            Rack object
        """
        rack_name = data.get('name')
        site_name = data.get('site')

        # Get site
        site = self.nb.dcim.sites.get(name=site_name)
        if not site:
            raise ValueError(f"Site '{site_name}' not found. Create site first.")

        # Prepare data with site ID
        data_copy = data.copy()
        data_copy["site"] = site.id

        # Resolve tenant if provided
        tenant_name = data.get('tenant')
        if tenant_name:
            tenant = self.nb.tenancy.tenants.get(name=tenant_name)
            if tenant:
                data_copy["tenant"] = tenant.id
            else:
                LOGGER.warning(f"Tenant '{tenant_name}' not found, creating rack without tenant")
                data_copy.pop('tenant', None)

        rack = next(
            iter(self.nb.dcim.racks.filter(name=rack_name, site_id=site.id)),
            None
        )

        if rack:
            LOGGER.info(f"Rack '{rack_name}' exists in site '{site_name}' (ID: {rack.id})")
            diff = self._compare_and_update(rack, data_copy, excluded_keys=['name', 'site', 'active'])
            if diff:
                return self._apply_update(rack, diff, f"rack '{rack_name}'")
            return rack

        LOGGER.info(f"Creating rack '{rack_name}' in site '{site_name}'")
        try:
            return self.nb.dcim.racks.create(data_copy)
        except Exception as e:
            raise Exception(
                f"Failed to create rack '{rack_name}' in site '{site_name}' because: {e}"
            )

    def create_or_update_module(self, data: dict):
        """Create or update a module and install it in a module bay.

        Args:
            data: Module data dictionary containing:
                - device: Device name where module bay is located
                - module_bay: Module bay name
                - module_type: Module type model name
                - serial: Serial number (optional)
                - asset_tag: Asset tag (optional)
                - status: Module status (active, planned, etc.)
                - description: Description (optional)

        Returns:
            Module object
        """
        device_name = data.get('device')
        bay_name = data.get('module_bay')
        module_type_name = data.get('module_type')
        module_type_path = data.get('module_type_path')

        if module_type_path:
            data.pop("module_type_path")

        # Get device
        device = self.nb.dcim.devices.get(name=device_name)
        if not device:
            raise ValueError(f"Object {device_name} is not created in Netbox.")

        # Get module bay
        module_bay = next(
            iter(self.nb.dcim.module_bays.filter(device_id=device.id, label=bay_name)),
            None
        )
        if not module_bay:
            raise Exception(
                f"Module bay '{bay_name}' not found on device '{device_name}'."
                "Create the module bay first."
            )

        # Get module type
        module_type = self.nb.dcim.module_types.get(model=module_type_name)
        if not module_type:
            try:
                from utils.functions import load_data_from_file
                module_type_data = load_data_from_file(
                    file_path=module_type_path,
                    file_extension="yaml"
                )
                module_type = self.create_or_update_module_type(module_type_data)
            except Exception as e:
                raise Exception(
                    f"Module type '{module_type_name}' not created."
                    f"{e}"
                )

        data_copy = data.copy()
        data_copy.update({
            "device": device.id,
            "module_bay": module_bay.id,
            "module_type": module_type.id
        })

        # check if module already installed in this bay
        existing_module = next(
            iter(self.nb.dcim.modules.filter(module_bay_id=module_bay.id)),
            None
        )
        if existing_module:
            LOGGER.info(f"Module exists in bay '{bay_name}' on device '{device_name}' (ID: {existing_module.id})")
            diff = self._compare_and_update(existing_module, data_copy, excluded_keys=['node'])
            if diff:
                return self._apply_update(existing_module, diff, f"module in bay '{bay_name}'")
            return existing_module

        LOGGER.info(f"Installing module '{module_type_name}' in bay '{bay_name}' on device '{device_name}'")
        # Before creating the module, filter existing interfaces.
        interfaces = data_copy.get("interfaces", [])
        filtered_interfaces = []

        for iface_template in interfaces:
            iface_name = iface_template["name"].replace("{module}", bay_name)
            existing_iface = next(
                iter(self.nb.dcim.interfaces.filter(device_id=device.id, name=iface_name)),
                None
            )
            if existing_iface:
                LOGGER.info(f"Interface '{iface_name}' already exists on device '{device_name}', skipping creation.")
                continue
            # add to the list of interfaces to be created
            filtered_interfaces.append(iface_template)

        # Update data_copy to keep only new interfaces
        data_copy["interfaces"] = filtered_interfaces
        print(json_dumps(data_copy, indent=2))
        try:
            return self.nb.dcim.modules.create(data_copy)
        except Exception as e:
            raise Exception(
                f"Failed to install module '{module_type_name}' in bay '{bay_name}' on device '{device_name}' because: {e}"
            ) from e


    def create_or_update_module_type(self, data: dict):
        """Create or update a module type with interface templates.

        Args:
            data: Module type data dictionary containing:
                - manufacturer: Manufacturer name
                - model: Module model name
                - part_number: Part number (optional)
                - description: Description (optional)
                - comments: Comments (optional)
                - weight: Weight value (optional)
                - weight_unit: Weight unit (optional)
                - interfaces: List of interface templates (optional)

        Returns:
            Module type object
        """
        manufacturer_name = data.get('manufacturer')
        model = data.get('model')
        manufacturer = self.nb.dcim.manufacturers.get(name=manufacturer_name)

        if not manufacturer:
            LOGGER.info(f"Auto-creating manufacturer '{manufacturer_name}'")
            manufacturer = self.nb.dcim.manufacturers.create({
                "name": manufacturer_name,
                "slug": manufacturer_name.lower().replace(' ', '-')
            })

        module_type = self.nb.dcim.module_types.get(model=model)
        data_copy = data.copy()
        data_copy["manufacturer"] = manufacturer.id

        # Extract interfaces for separate handling
        interfaces = data_copy.pop('interfaces', None)
        if module_type:
            LOGGER.info(f"Module type '{model}' exists (ID: {module_type.id})")
            # Update module type attributes
            diff = self._compare_and_update(
                module_type,
                data_copy,
                excluded_keys=['model', 'manufacturer']
            )
            if diff:
                module_type = self._apply_update(module_type, diff, f"module type '{model}'")

            return module_type

        # Create new module type
        LOGGER.info(f"Creating module type '{model}'")
        module_type = self.nb.dcim.module_types.create(data_copy)

        # Create interface templates
        if interfaces:
            self._sync_module_type_interface_templates(module_type, interfaces, model)

        return module_type

    #==========================================================================================
    def create_or_update_inventory_item(self, data: dict):
        """Create or update an inventory item."""
        device_name = data.get('device')
        item_name = data.get('name')

        if not device_name or not item_name:
            raise Exception("Device name and item name are required")

        # Retrieve the device
        device = self.nb.dcim.devices.get(name=device_name)
        if not device:
            raise Exception(f"Device '{device_name}' not found")

        # Search for an existing inventory item
        inventory_item = self.nb.dcim.inventory_items.get(
            device_id=device.id,
            name=item_name
        )

        if inventory_item:
            LOGGER.info(f"Inventory item '{item_name}' exists on device '{device_name}' (ID: {inventory_item.id})")

            try:
                # Prepare the data for the update
                data_copy = self._prepare_inventory_item_data(data, device.id)

                diff = self._compare_and_update(
                    inventory_item,
                    data_copy,
                    excluded_keys=['name', 'device']
                )

                if diff:
                    return self._apply_update(inventory_item, diff, f"inventory item '{item_name}' on device '{device_name}'")

                LOGGER.info(f"Inventory item '{item_name}' is already up to date")
                return inventory_item

            except Exception as e:
                raise Exception(f"Failed to update inventory item '{item_name}' on device '{device_name}': {e}") from e

        # Create a new inventory item
        try:
            data_prepared = self._prepare_inventory_item_data(data, device.id, validate_required=True)
            LOGGER.info(f"Creating inventory item '{item_name}' on device '{device_name}'")
            LOGGER.info(json_dumps(data_prepared, indent=2))
            return self.nb.dcim.inventory_items.create(data_prepared)
        except Exception as e:
            raise Exception(f"Failed to create inventory item '{item_name}' on device '{device_name}': {e}") from e

    def _prepare_inventory_item_data(self, data: dict, device_id: int, validate_required: bool = False):
        """Prepare inventory item data for NetBox API."""
        prepared_data = {}

        # Required fields
        if validate_required:
            if 'name' not in data:
                raise Exception("Field 'name' is required")

        # Device (required)
        prepared_data['device'] = device_id

        # Name
        if 'name' in data:
            prepared_data['name'] = data['name']

        # Parent inventory item (optional)
        if 'parent' in data:
            parent_name = data['parent']
            parent_item = self.nb.dcim.inventory_items.get(
                device_id=device_id,
                name=parent_name
            )
            if parent_item:
                prepared_data['parent'] = parent_item.id
            else:
                LOGGER.warning(f"Parent inventory item '{parent_name}' not found on device")

        # Manufacturer (optionnel)
        if 'manufacturer' in data:
            manufacturer_name = data['manufacturer']
            manufacturer = self.nb.dcim.manufacturers.get(name=manufacturer_name)
            if not manufacturer:
                LOGGER.info(f"Auto-creating manufacturer '{manufacturer_name}'")
                manufacturer = self.nb.dcim.manufacturers.create({
                    "name": manufacturer_name,
                    "slug": manufacturer_name.lower().replace(' ', '-')
                })
            prepared_data['manufacturer'] = manufacturer.id

        # Role (optionnel)
        if 'role' in data:
            role_name = data['role']
            role = self.nb.dcim.inventory_item_roles.get(name=role_name)
            if not role:
                LOGGER.info(f"Auto-creating inventory item role '{role_name}'")
                role = self.nb.dcim.inventory_item_roles.create({
                    "name": role_name,
                    "slug": role_name.lower().replace(' ', '-')
                })
            prepared_data['role'] = role.id

        if 'component_id' in data:
            component_id = data['component_id']
            if component_id:
                interface = next(
                    iter(self.nb.dcim.interfaces.filter(device_id=device_id, name=component_id)),
                    None
                )
            prepared_data['component_id'] = interface.id

        # Simple fields
        simple_fields = [
            'label',
            'part_id',
            'component_type',
            'serial',
            'asset_tag',
            'discovered',
            'description',
        ]

        for field in simple_fields:
            if field in data:
                prepared_data[field] = data[field]

        # Custom fields (optionnel)
        if 'custom_fields' in data:
            prepared_data['custom_fields'] = data['custom_fields']

        # Tags (optionnel)
        if 'tags' in data:
            tags = []
            for tag_name in data['tags']:
                tag = self.nb.extras.tags.get(name=tag_name)
                if not tag:
                    LOGGER.info(f"Auto-creating tag '{tag_name}'")
                    tag = self.nb.extras.tags.create({
                        "name": tag_name,
                        "slug": tag_name.lower().replace(' ', '-')
                    })
                tags.append({"name": tag.name})
            prepared_data['tags'] = tags

        return prepared_data
    #==========================================================================================

    def _sync_module_type_interface_templates(
        self,
        module_type: Any,
        interfaces: list,
        model_name: str
    ) -> None:
        """Sync interface templates for a module type.

        Args:
            module_type: Module type object
            interfaces: List of interface template dictionaries
            model_name: Module type model name (for logging)
        """
        if not interfaces:
            return

        # Get existing interface templates
        existing_templates = list(
            self.nb.dcim.interface_templates.filter(module_type_id=module_type.id)
        )

        # Create mapping of existing templates by name
        existing_by_name = {tmpl.name: tmpl for tmpl in existing_templates}

        # Track templates from YAML
        yaml_template_names = set()

        # Create or update templates
        for intf in interfaces:
            intf_name = intf.get('name')
            intf_type = intf.get('type')

            yaml_template_names.add(intf_name)

            # Prepare template data
            template_data = {
                "module_type": module_type.id,
                "name": intf_name,
                "type": intf_type,
            }

            if intf_name in existing_by_name:
                # Update existing template
                existing_tmpl = existing_by_name[intf_name]

                # Check if update needed
                if existing_tmpl.type != intf_type:
                    try:
                        existing_tmpl.type = intf_type
                        existing_tmpl.save()
                        LOGGER.info(
                            f"  ✓ Updated interface template '{intf_name}' "
                            f"for module type '{model_name}'"
                        )
                    except Exception as e:
                        LOGGER.warning(
                            f"  ⚠ Failed to update interface template '{intf_name}': {e}"
                        )
            else:
                # Create new template
                try:
                    self.nb.dcim.interface_templates.create(template_data)
                    LOGGER.info(
                        f"  ✓ Created interface template '{intf_name}' "
                        f"for module type '{model_name}'"
                    )
                except Exception as e:
                    LOGGER.warning(
                        f"  ⚠ Failed to create interface template '{intf_name}': {e}"
                    )

        # Optional: Delete templates not in YAML (commented out for safety)
        # for tmpl_name, tmpl in existing_by_name.items():
        #     if tmpl_name not in yaml_template_names:
        #         try:
        #             tmpl.delete()
        #             LOGGER.info(
        #                 f"  ✓ Deleted interface template '{tmpl_name}' "
        #                 f"from module type '{model_name}'"
        #             )
        #         except Exception as e:
        #             LOGGER.warning(
        #                 f"  ⚠ Failed to delete interface template '{tmpl_name}': {e}"
        #             )

        LOGGER.info(
            f"✓ Synced {len(interfaces)} interface templates for module type '{model_name}'"
        )

class Trigger_helper:
    """Helper class for pyATS trigger operations.

    Provides utility methods for device connection management with
    automatic retry logic and proxy support.

    Attributes:
        logger: Logger instance for connection status messages.

    Exceptions:
        ConnectionFailedException: Raised when device connection fails
            after all retry attempts.

    Example:
        ```python
        from utils.classes import Trigger_helper

        # Connect with retry logic
        Trigger_helper.connect(
            device=router,
            max_retries=3,
            retry_sleep=5
        )
        ```
    """

    class ConnectionFailedException(Exception):
        """Exception raised when device connection fails after all retries."""
        pass

    @classmethod
    def connect(
        cls,
        device=None,
        logger=GetLogger.init_log(),
        retry_sleep=2,
        max_retries=3,
        proxy=None,
        via="vty",
        **kwargs
    ):
        """Connect to a device with automatic retry on failure.

        Attempts to establish a connection to a pyATS device, retrying
        on failure with configurable sleep intervals. Supports proxy
        connections and SSH key scanning.

        Args:
            device: pyATS device object to connect to.
            logger (logging.Logger, optional): Logger for connection status.
                Defaults to GetLogger.init_log().
            retry_sleep (int, optional): Seconds to wait between retries.
                Defaults to 2.
            max_retries (int, optional): Maximum connection attempts.
                Defaults to 2.
            proxy: pyATS device object to use as SSH proxy/jumphost.
                Defaults to None.
            via (str, optional): Connection method name from device
                connections. Defaults to "vty".
            **kwargs: Additional arguments passed to device.connect().

        Raises:
            ConnectionFailedException: If connection fails after all retries.

        Example:
            ```python
            # Direct connection
            Trigger_helper.connect(device=router, max_retries=3)

            # Connection via proxy/jumphost
            Trigger_helper.connect(
                device=router,
                proxy=jumphost,
                via="vty"
            )
            ```
        """
        if "log_stdout" not in kwargs:
            kwargs.update({
                "log_stdout": True}
            )
        if logger:
            cls.logger = logger

        retry_counter = 0
        successful_connection = False
        error_log = ""

        while not successful_connection:
            retry_counter += 1
            cls.logger.info(
                f'Attempting connection to device: {device.name}... Retry #°{retry_counter}')

            # try with a semaphor instead of retry loop
            try:
                if proxy:
                    device.host = getattr(getattr(device.connections, via, None), "host")
                    ssh_key_remove = f"ssh-keygen -R {device.host} 2>/dev/null"
                    ssh_keyscan = f"ssh-keyscan -H {device.host} >> ~/.ssh/known_hosts 2>/dev/null"
                    proxy.connect()
                    proxy.execute(ssh_key_remove)
                    proxy.execute(ssh_keyscan)
                device.connect(
                    via=via,
                    **kwargs
                )
            except Exception as e:
                error_log = f"Device '{device.name}' failed to connect: {e}"

            if device.is_connected():
                successful_connection = True
                break
            if retry_counter >= max_retries:
                break

            cls.logger.info(f'Sleeping for: {retry_sleep}s...')
            sleep(retry_sleep)
        # when while loop is done, check if the connection was successful
        # otherwise raise ConnectionFailedException
        if not successful_connection:
            raise Trigger_helper.ConnectionFailedException(error_log)

class Transformer:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def transforme(self, type_="racktables"):
        def racktables():
            """
            Performs the RackTables -> NetBox transformation using RackTablesTransformer.
            """
            try:
                gathering_racktables_data(logger=LOGGER, device_roles=self.device_roles)
            except Exception as e:
                LOGGER.error("Failure to launch data collection via racktable")
                return 1
            # -----------------------------------
            # Load RackTables input
            # -----------------------------------
            LOGGER.info("Loading RackTables Json data...")
            start = time()
            try:
                from utils.functions import find_racktable_file
                raw_data_path = find_racktable_file(
                    directory=self.ractable_data_path,
                    prefix=self.raw
                )
                with open(raw_data_path, "r", encoding="utf-8") as f:
                    rack_data = js_load(f)
            except Exception as e:
                LOGGER.error(f"Can't load RackTables JSON: {e}")
                sys.exit(1)

            LOGGER.info(f"Load completed in {time() - start:.2f}s")

            # ------------------------------------
            # Transform RackTables
            # ------------------------------------
            LOGGER.info("Processing RackTables transformation...")
            start = time()
            from transformers.racktables import RackTablesTransformer
            transformer = RackTablesTransformer(
                mapping=self.mapping,
                site="Demo-lab",
                testbed=self.testbed,
                filter_devices=getattr(self, 'filter_by_devices', None)
            )
            self.result = transformer.process(source_data=rack_data)
            LOGGER.info(f"RackTables transformation done in {time() - start:.2f}s")

            # ------------------------------------
            # Export YAML
            # ------------------------------------
            LOGGER.info("Saving NetBox YAML output...")
            start = time()
            try:
                from utils.functions import save_yaml
                for obj, obj_data in self.netbox_obj_definition.items():
                    if obj not in ['module_types', 'device_types']:
                        data_path = obj_data.get('path')
                        if not data_path:
                            LOGGER.warning(f"No path defined for object {obj}, skipping.")
                            continue

                        data = self.result.get(obj) if self.result.get(obj) else self.cfg.get(obj)
                        if not data:
                            LOGGER.info(f"No data to write for {obj}, skipping.")
                            continue
                        save_yaml(data_path=data_path, data=data, merge=True)
            except Exception as e:
                LOGGER.error(f"Failed to save YAML: {e}")
                sys.exit(1)

            LOGGER.info(f"YAML generation completed in {time() - start:.2f}s")
            LOGGER.info(f"✓ Output written to common/data/netbox/")
            LOGGER.info(f"✓ Devices processed: {len(self.result.get('devices'))}") if 'devices' in self.result else ''

        locals()[type_]()

########################################################################
class PolatisManager:
    """Manager pour gérer les connexions Polatis et mettre à jour NetBox."""

    def __init__(
        self,
        polatis_address: str,
        polatis_username: str,
        polatis_password: str,
        polatis_device_name: str,
        racktables_data_path: str,
        interface_abbreviation_mapping: dict,
        testbed: Optional[object] = None
    ):
        """Initialize Polatis Manager.

        Args:
            polatis_address: IP/hostname du switch Polatis
            polatis_username: Username pour connexion
            polatis_password: Password pour connexion
            polatis_device_name: Nom du device Polatis dans RackTables
            racktables_data_path: Chemin vers les données RackTables
            interface_abbreviation_mapping: Table de mapping des abréviations
            testbed: Objet testbed PyATS (optionnel)
        """
        self.polatis_address = polatis_address
        self.polatis_username = polatis_username
        self.polatis_password = to_plaintext(polatis_password)
        self.polatis_device_name = polatis_device_name
        self.racktables_data_path = racktables_data_path
        self.interface_abbreviation_mapping = interface_abbreviation_mapping
        self.testbed = testbed

        self.polatis = None
        self.port_mapping = {}
        self.connections = {}

    def connect(self) -> bool:
        """Connect to Polatis switch.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            LOGGER.info(f"Connecting to Polatis at {self.polatis_address}...")
            self.polatis = Polatis(self.polatis_address, self.polatis_username)
            self.polatis.connect(self.polatis_password)
            LOGGER.info("✓ Successfully connected to Polatis")
            return True
        except Exception as e:
            LOGGER.error(f"✗ Failed to connect to Polatis: {e}")
            return False

    def disconnect(self) -> bool:
        """Disconnect from Polatis switch.

        Returns:
            True if disconnection successful, False otherwise
        """
        try:
            if self.polatis:
                self.polatis.logout()
                LOGGER.info("✓ Disconnected from Polatis")
                return True
        except Exception as e:
            LOGGER.error(f"✗ Failed to disconnect from Polatis: {e}")
            return False

    def load_racktables_data(self) -> dict:
        """Load RackTables data from JSON file.

        Returns:
            RackTables data dictionary

        Raises:
            FileNotFoundError: If RackTables file not found
            json.JSONDecodeError: If file is not valid JSON
        """
        try:
            LOGGER.info(f"Loading RackTables data from {self.racktables_data_path}...")
            from utils.functions import find_racktable_file
            # Find racktables file
            raw_data_path = find_racktable_file(
                directory=self.racktables_data_path,
                prefix='racktables-data'
            )

            with open(raw_data_path, "r", encoding="utf-8") as f:
                rack_data = json.load(f)

            LOGGER.info(f"✓ Loaded RackTables data: {len(rack_data)} objects")
            return rack_data

        except Exception as e:
            LOGGER.error(f"✗ Failed to load RackTables data: {e}")
            raise

    def build_polatis_port_mapping(self, rack_data: dict) -> dict:
        """Build mapping of Polatis port number -> remote device/interface.

        RT stores port names as zero-padded 3-digit strings ("025"), while the
        Polatis SDK returns integers (25). This function normalizes to string
        without padding ("25").

        Args:
            rack_data: RackTables data dictionary

        Returns:
            Port mapping: {port_num_str: {device, interface, cable}}
        """
        LOGGER.info(f"Building port mapping for Polatis device '{self.polatis_device_name}'...")

        # Find the Polatis object by name (case-insensitive)
        polatis_obj = None
        for _, obj in rack_data.items():
            if obj.get('name', '').lower() == self.polatis_device_name.lower():
                polatis_obj = obj
                break

        if not polatis_obj:
            LOGGER.warning(
                f"Polatis device '{self.polatis_device_name}' not found in RackTables data"
            )
            return {}

        # Build port mapping from virtual_port links
        # Polatis has ingress ports (1-384) and egress ports (385-768).
        # RT stores only ingress port numbers (001-384) with a label field
        # "ingress.egress" (e.g. "038.422" means ingress 38 is paired with egress 422).
        port_mapping = {}

        for iface in polatis_obj.get('interfaces', []):
            port_name = iface.get('if_name', '')
            try:
                ingress_port = str(int(port_name))  # "038" -> "38"
            except ValueError:
                continue

            vport = iface.get('virtual_port', {})
            if vport and 'remote_device_name' in vport:
                device_info = {
                    'device': vport['remote_device_name'],
                    'interface': vport['remote_port_name'],
                    'cable': vport.get('cable', ''),
                }
                # Map ingress port directly
                port_mapping[ingress_port] = device_info

                # Parse label from physical_port to find paired egress port
                pport = iface.get('physical_port', {})
                label = pport.get('local_port_label', '')
                if '.' in label:
                    try:
                        egress_port = str(int(label.split('.')[1]))
                        port_mapping[egress_port] = device_info
                    except (ValueError, IndexError):
                        pass

        LOGGER.info(
            f"✓ Built port mapping for {self.polatis_device_name}: "
            f"{len(port_mapping)} ports mapped"
        )
        return port_mapping

    def get_polatis_connections(self) -> list:
        """Get all active cross-connections from Polatis.

        Returns:
            List of connections: [(port_in, port_out), ...]

        Raises:
            Exception: If failed to retrieve connections
        """
        try:
            LOGGER.info("Retrieving all active cross-connections from Polatis...")
            raw_connections = self.polatis.get_all_connections()
            LOGGER.info(f"✓ Retrieved {len(raw_connections)} connections")
            return raw_connections
        except Exception as e:
            LOGGER.error(f"✗ Failed to retrieve connections: {e}")
            raise

    def build_enriched_connections(self, raw_connections: list) -> dict:
        """Build enriched connection dict with device/interface info.

        Args:
            raw_connections: List of raw connections from Polatis

        Returns:
            Enriched connections dict: {
                port_in_str: {
                    port_in, port_out,
                    device_in, interface_in, cable_in,
                    device_out, interface_out, cable_out
                }
            }
        """
        LOGGER.info("Building enriched connections with device/interface info...")

        connections = {}

        for conn in raw_connections:
            port_in = conn[0]
            port_out = conn[1]

            in_info = self.port_mapping.get(str(port_in), {})
            out_info = self.port_mapping.get(str(port_out), {})

            connections[str(port_in)] = {
                'port_in': port_in,
                'port_out': port_out,
                'device_in': in_info.get('device', ''),
                'interface_in': in_info.get('interface', ''),
                'cable_in': in_info.get('cable', ''),
                'device_out': out_info.get('device', ''),
                'interface_out': out_info.get('interface', ''),
                'cable_out': out_info.get('cable', ''),
            }

        LOGGER.info(f"✓ Built {len(connections)} enriched connections")
        return connections

    def update_interfaces_from_polatis(
        self,
        interfaces: Dict[str, List[dict]],
        polatis_connections: dict
    ) -> Dict[str, List[dict]]:
        """Update interfaces with remote device/port from Polatis data.

        Args:
            interfaces: Dict of interfaces by device
            polatis_connections: Enriched Polatis connections

        Returns:
            Updated interfaces dict
        """
        LOGGER.info("Updating interfaces with Polatis connection data...")

        result = copy.deepcopy(interfaces)
        update_count = 0

        for device, iface_list in result.items():
            for iface in iface_list:
                cf = iface.get("custom_fields", {})
                remote_device_name = cf.get("remote_device")
                remote_port = cf.get("remote_port_name")

                if not remote_device_name or not remote_port or "polatis" not in remote_device_name.lower():
                    continue

                if remote_port is not None and str(remote_port) in polatis_connections:
                    polatis_entry = polatis_connections[str(remote_port)]

                    if polatis_entry.get("port_in") == int(remote_port):
                        # Get device OS for interface normalization
                        device_os = None
                        if self.testbed and hasattr(self.testbed, 'devices'):
                            remote_device = polatis_entry["device_out"]
                            if remote_device in self.testbed.devices:
                                device_os = self.testbed.devices[remote_device].os

                        # Update remote device
                        cf["remote_device"] = polatis_entry["device_out"]
                        from utils.functions import normalize_interface_name
                        # Normalize and update remote interface name
                        cf["remote_port_name"] = normalize_interface_name(
                            intf=polatis_entry["interface_out"],
                            intf_abbrv_mapping_table=self.interface_abbreviation_mapping,
                            os=device_os
                        )

                        update_count += 1
                        LOGGER.info(
                            f"Updated {device}/{iface['name']}: "
                            f"remote = {cf['remote_device']}/{cf['remote_port_name']}"
                        )

        LOGGER.info(f"✓ Updated {update_count} interfaces with Polatis data")
        return result

    def load_interfaces_yaml(self, filepath: str) -> dict:
        """Load interfaces from YAML file.

        Args:
            filepath: Path to interfaces YAML file

        Returns:
            Interfaces dictionary
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                interfaces = yaml.safe_load(f)
            LOGGER.info(f"✓ Loaded interfaces from {filepath}")
            return interfaces
        except Exception as e:
            LOGGER.error(f"✗ Failed to load interfaces: {e}")
            raise

    def save_interfaces_yaml(
        self,
        interfaces: dict,
        filepath: str
    ) -> None:
        """Save interfaces to YAML file.

        Args:
            interfaces: Interfaces dictionary
            filepath: Output file path
        """
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                yaml.dump(
                    interfaces,
                    f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False
                )
            LOGGER.info(f"✓ Saved interfaces to {filepath}")
        except Exception as e:
            LOGGER.error(f"✗ Failed to save interfaces: {e}")
            raise

    def process(self, interfaces_yaml_path: str) -> dict:
        """Process complete Polatis workflow.

        This is the main method that orchestrates:
        1. Connect to Polatis
        2. Load RackTables data
        3. Build port mapping
        4. Get connections
        5. Update interfaces
        6. Save results

        Args:
            interfaces_yaml_path: Path to interfaces YAML file

        Returns:
            Updated interfaces dictionary
        """
        try:
            # Step 1: Connect to Polatis
            if not self.connect():
                raise Exception("Failed to connect to Polatis")

            # Step 2: Load RackTables data
            rack_data = self.load_racktables_data()

            # Step 3: Build port mapping
            self.port_mapping = self.build_polatis_port_mapping(rack_data)

            # Step 4: Get Polatis connections
            raw_connections = self.get_polatis_connections()

            # Step 5: Build enriched connections
            self.connections = self.build_enriched_connections(raw_connections)

            # Optional: Log connections for debugging
            LOGGER.debug("Polatis connections:")
            LOGGER.debug(json.dumps(self.connections, indent=2))

            # Step 6: Load existing interfaces
            interfaces = self.load_interfaces_yaml(interfaces_yaml_path)

            # Step 7: Update interfaces with Polatis data
            updated_interfaces = self.update_interfaces_from_polatis(
                interfaces,
                self.connections
            )

            # Step 8: Save updated interfaces
            self.save_interfaces_yaml(updated_interfaces, interfaces_yaml_path)

            LOGGER.info("✓ Polatis processing completed successfully")

            return updated_interfaces

        except Exception as e:
            LOGGER.error(f"✗ Polatis processing failed: {e}")
            raise

        finally:
            # Always disconnect
            self.disconnect()