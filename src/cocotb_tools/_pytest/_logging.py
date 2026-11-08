
# Copyright cocotb contributors
# Licensed under the Revised BSD License, see LICENSE for details.
# SPDX-License-Identifier: BSD-3-Clause

"""Everything related with logging."""

from __future__ import annotations

import logging
from logging import (
    Filter,
    LogRecord,
    getLogger,
    getLogRecordFactory,
    setLogRecordFactory,
)
from typing import Callable

from _pytest.logging import DEFAULT_LOG_FORMAT, LoggingPlugin
from pytest import Config, Session, hookimpl

import cocotb
import cocotb.simtime
from cocotb.simtime import get_sim_time

COCOTB_LOG_FORMAT: str = (
    "%(sim_time_str)8s%(sim_time_unit)s %(levelname)-8s %(name)s %(message)s"
)


def get_level(name: str) -> int:
    """Get log level based on provided name.

    Args:
        name: Name of log level.

    Returns:
        Integer value of log level.
    """
    return getattr(logging, name.upper(), 0)


class SimContextFilter(Filter):
    """Attach information about simulation to log record using log filter."""

    def __init__(self) -> None:
        """Create new instance of simulation context filter."""
        self._is_simulation: bool = getattr(cocotb, "is_simulation", False)

    def filter(self, record: LogRecord) -> bool:
        """Attach information about simulation to log record."""
        if not hasattr(record, "sim_time"):
            sim_time: int | float | None = self._get_sim_time()
            record.sim_time_unit = cocotb.simtime.report_precision

            if sim_time is None:
                record.sim_time = 0
                record.sim_time_str = "-.--"
            else:
                record.sim_time = sim_time
                record.sim_time_str = f"{sim_time:.2f}"

        return True

    def _get_sim_time(self) -> int | float | None:
        if self._is_simulation:
            try:
                return get_sim_time(cocotb.simtime.report_precision)
            except RecursionError:
                pass  # If get_sim_time will try to log

        return None


class Logging:
    """Logging plugin to configure logging in pytest environment."""

    def __init__(self, config: Config) -> None:
        """Create new instance of logging plugin."""
        self._filter: Filter = SimContextFilter()

        # Keep track of the handlers that receive Cocotb's filter.
        # This allows us to remove only our filter during cleanup.
        #introduced a list to remember the four pytest handlers.
        #remove Cocotb's filter from those exact handlers later.
        
        self._handlers: list[logging.Handler] = []

        option = config.option

        if not option.log_format and config.getini("log_format") is DEFAULT_LOG_FORMAT:
            option.log_format = COCOTB_LOG_FORMAT

        # Save the factory that was active before Cocotb modified it.
        # Restoring this factory prevents Cocotb's global logging change
        # from affecting other pytest sessions or applications.
        #Instead of just retrieving the existing factory into a temporary variable, we now save it as an instance attribute.
        self._original_log_record_factory: Callable[..., LogRecord] = (
            getLogRecordFactory()
        )

        # Preserve the existing factory's behavior and add simulation
        # context information to every newly created log record.
        #The wrapper now explicitly uses the factory saved above
        #To ensure Cocotb's custom factory wraps the original factory rather than accidentally wrapping itself or another later reference.
        create_log_record: Callable[..., LogRecord] = (
            self._original_log_record_factory
        )

        def log_record_factory(*args: object, **kwargs: object) -> LogRecord:
            record: LogRecord = create_log_record(*args, **kwargs)
            self._filter.filter(record)
            return record

        # Keep a reference to our factory so cleanup can check whether
        # it is still installed before attempting to restore the original.
        
        self._log_record_factory = log_record_factory#save the custom factory in self._log_record_factory
        setLogRecordFactory(self._log_record_factory) #install that saved reference as Later, during cleanup, you need to identify whether the factory currently installed is actually Cocotb's factory.

        if option.gpi_log_level:
            getLogger("gpi").setLevel(get_level(option.gpi_log_level))

        if option.cocotb_log_level:
            getLogger("cocotb").setLevel(get_level(option.cocotb_log_level))

    @hookimpl(tryfirst=True)
    def pytest_sessionstart(self, session: Session) -> None:
        """Called after the pytest.Session object has been created."""

        config: Config = session.config
        plugin: LoggingPlugin | None = config.pluginmanager.get_plugin(
            "logging-plugin"
        )

        if plugin:
            # Pytest uses four handlers for different logging destinations.
            # Track all four so Cocotb can remove its filter from each one.
            #Previously, code had  attached the filter directly to each handler.
            #Now, first save all four handler references and then attach the filter using a loop.
            #So the cleanup method knows exactly which handlers to clean.
            
            self._handlers = [
                plugin.log_file_handler,
                plugin.log_cli_handler,
                plugin.caplog_handler,
                plugin.report_handler,
            ]

            for handler in self._handlers:
                handler.addFilter(self._filter)

    #Cleanup
    @hookimpl
    def pytest_sessionfinish(
        self, session: Session, exitstatus: int
    ) -> None:
        """Restore logging state after the pytest session finishes."""

        #Factory restoration
        # Restore the original factory only if Cocotb's factory is still
        # installed. Another plugin may have replaced it in the meantime.
        if getLogRecordFactory() is self._log_record_factory:
            setLogRecordFactory(self._original_log_record_factory)

        # Remove only Cocotb's filter, leaving other plugins' filters intact.
        for handler in self._handlers:#remove filters from handlers
            handler.removeFilter(self._filter)
