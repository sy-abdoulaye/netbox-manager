from typing import Any, Callable, Dict, List
from utils.functions import export_to_json

class BaseTransformer:
    """
    Generic base class for all transformations
    Each subclass must define:
        - pipeline() -> list of functions
        - transform_* functions that feed self.result
    """

    def __init__(self, mapping: Dict, testbed, site: str = "demo-lab", filter_devices=None):
        self.mapping = mapping
        self.site = site
        self.testbed = testbed
        # Normalise en liste si une seule valeur est passée (ex: depuis CLI)
        if isinstance(filter_devices, str):
            filter_devices = [filter_devices]
        self.filter_devices: List[str] | None = filter_devices or None

        self.platforms = self.mapping.get('supported_platforms')

        # source_data is filled when calling .process()
        self.source_data: Dict[str, Any] = {}

        #  final result of the transformation
        self.result: Dict[str, Any] = {}

    def pipeline(self) -> List[Callable]:
        """
        Must return a list of methods in the order of execution.
            Example in a child transformer:
            return [self.transform_devices, self.transform_interfaces]
        """
        return []

    def process(self, source_data: Dict) -> Dict:
        """
        Single entry point: executes the transformation pipeline.
        """
        self.source_data = source_data
        self.result: Dict[str, Any] = {}
        excluded_devices: Dict[str, Dict] = {}

        for idx, data in source_data.items():
            error = self._validate_device(data)
            if error:
                excluded_devices[idx] = error
                continue

            for step in self.pipeline():
                not_compliance = step(data)
                if not_compliance:
                    excluded_devices[idx] = not_compliance

        self._export_excluded_devices(excluded_devices)
        return self.result

    def _validate_device(self, data: Dict) -> Dict | None:
        device_name = data.get("name")
        hw_type = str(data.get("HW_type", "")).strip()
        device_status = str(data.get("Etat_Equipement", "")).casefold()

        if not device_name or not hw_type or device_status != "en service":
            return self._exclude_device(
                data,
                f"The equipment status must be 'en service' and HW_type must not be null. So device: {device_name} has hw_type: {hw_type} and status:{device_status}"
            )

        if self.filter_devices and device_name not in self.filter_devices:
            return self._exclude_device(
                data,
                f"Device '{device_name}' excluded by --filter-by-devices filter."
            )

        device = self.testbed.devices.get(device_name)
        if not device:
            return self._exclude_device(
                data,
                f"The device '{device_name}' does not exist in ./testbed/testbed.yaml."
            )

        if device.os not in self.platforms:
            return self._exclude_device(
                data,
                (
                    f"The device '{device_name}' platform '{device.os}' is not supported. "
                    f"Add it to supported_platforms in common/config/mapping_data.yaml."
                )
            )

        return None

    def _exclude_device(self, data: Dict, reason: str) -> Dict:
        excluded = data.copy()
        excluded["fixed"] = reason
        return excluded

    def _export_excluded_devices(self, excluded_devices: Dict) -> None:
        if not excluded_devices:
            return

        filepath = export_to_json(
            results_dir="./common/data/excluded_devices",
            filename="racktables_data",
            data=excluded_devices,
        )

        print(f"Devices not sent to netbox are saved in this file {filepath}.")
