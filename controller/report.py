"""Report generation module for network automation results."""
from contextlib import contextmanager
from typing import Dict, Any, Optional
from pathlib import Path
import json
from utils.classes import GetLogger

LOGGER = GetLogger.init_log()


@contextmanager
def safe_lock(lock):
    """
    Context manager for safe lock acquisition and release.

    Args:
        lock: Lock object (can be None for non-threaded operations)

    Yields:
        None
    """
    acquired = False
    try:
        if lock:
            lock.acquire()
            acquired = True
        yield
    finally:
        if lock and acquired:
            try:
                lock.release()
            except Exception as e:
                LOGGER.warning(f"Failed to release lock: {e}")

class Report:
    """
    Report generator for network automation test results.

    Supports YAML and JSON output formats with thread-safe file operations.
    """

    SUPPORTED_FORMATS = {'yaml', 'json', 'html'}

    def __init__(self, *args, **kwargs):
        """
        Initialize the report generator.

        Args:
            **kwargs: Report parameters (action, build_id, build_user_id, path, lock)
        """
        # Dynamically set attributes from kwargs
        for key, value in kwargs.items():
            setattr(self, key.replace("-", "_"), value)

        self.raw_data = {}
        self.data = {}

    def generate(
        self,
        format_type: str = 'yaml',
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Generate report in the specified format.

        Args:
            format_type: Output format ('yaml', 'json', 'html')
            data: Optional data to use instead of self.data

        Raises:
            NotImplementedError: If format type is not supported
        """
        format_type = format_type.lower()

        if format_type not in self.SUPPORTED_FORMATS:
            raise NotImplementedError(
                f"Report format '{format_type}' is not supported. "
                f"Supported formats: {', '.join(self.SUPPORTED_FORMATS)}"
            )

        # Call the appropriate generator method
        generator_map = {
            'yaml': self._generate_yaml,
            # 'json': self._generate_json,
            # 'html': self._generate_html,
        }

        generator_map[format_type](data)

    def _generate_yaml(self, data: Optional[Dict[str, Any]] = None) -> None:
        """
        Generate YAML report with merge capability.

        Args:
            data: Optional data to merge with existing report
        """
        from utils.functions import deep_merge, load_data_from_file, update_yaml

        report_filename = (
            f'{self.trigger_name}.yaml'
        )
        report_path = Path(self.path) / report_filename

        LOGGER.info(f"Generating YAML report: {report_path}")

        with safe_lock(getattr(self, 'lock', None)):
            from utils.functions import path_exists
            try:
                # Determine if we need to create the file
                create_file = True

                # Load existing data if file exists
                if path_exists(report_path, is_file=True):
                    create_file = False
                    LOGGER.info(f"Loading existing report: {report_path}")
                    try:
                        self.raw_data = load_data_from_file(
                            file_extension="yaml",
                            data=self.raw_data,
                            file_path=str(report_path),
                        )
                    except Exception as e:
                        LOGGER.error(f"Failed to load existing report: {e}")
                        # Start fresh if load fails
                        self.raw_data = {}
                        create_file = True

                # Merge new data with existing data
                data_to_merge = data if data is not None else getattr(self, "data", {})

                if data_to_merge:
                    LOGGER.info("Merging new data with existing report")
                    deep_merge(data_to_merge, self.raw_data, no_list_dups=True)

                # Write updated data to file
                LOGGER.debug(f"Writing report to: {report_path}")
                update_yaml(
                    data=self.raw_data,
                    file=str(report_path),
                    create=create_file
                )

                LOGGER.info(f"✓ YAML report generated successfully: {report_path}")
            except Exception as e:
                LOGGER.error(f"Failed to generate YAML report: {e}")
                raise


