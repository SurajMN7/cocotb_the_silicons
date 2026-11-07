# Copyright cocotb contributors
# Licensed under the Revised BSD License, see LICENSE for details.
# SPDX-License-Identifier: BSD-3-Clause

"""Everything related with logging."""

from __future__ import annotations

import logging
from logging import (
    Filter,             #A filter is an object that examines a log record,it can modify, allow, reject the rcord
    LogRecord,          #This is the actual object representing a logging event.
                        #Python internally creates a LogRecord everytime this is typed
    getLogger,          #Gets the logger named "cocotb".
    getLogRecordFactory,#Gets the function currently responsible for creating LogRecord objects.
    setLogRecordFactory,#Allows us to install our own LogRecord creation function.
)
from typing import Callable

from _pytest.logging import DEFAULT_LOG_FORMAT, LoggingPlugin
from pytest import Config, Session, hookimpl

import cocotb                        #Main Cocotb package
import cocotb.simtime                #Simulation-time functionality.
from cocotb.simtime import get_sim_time  #Retrieves the current simulation time.

COCOTB_LOG_FORMAT: str = (            
    "%(sim_time_str)8s%(sim_time_unit)s %(levelname)-8s %(name)s %(message)s"
)

# following converts a user-friendly logging-level name into the integer value Python's logging system understands
#The function is small, but it acts as a bridge between user configuration and Python's logging API.
def get_level(name: str) -> int:
    """Get log level based on provided name.

    Args:
        name: Name of log level.

    Returns:
        Integer value of log level.
    """
    return getattr(logging, name.upper(), 0)

#The problem is that Python doesn't automatically know Cocotb's simulation time.
#So we create a custom filter that adds this information to the log record.

class SimContextFilter(Filter):#we plan to reuse the Filter class and customise it
    """Attach information about simulation to log record using log filter."""

    def __init__(self) -> None:
        """Create new instance of simulation context filter."""
        self._is_simulation: bool = getattr(cocotb, "is_simulation", False)
        #Does the Cocotb module have an attribute called is_simulation? If yes, give me its value. Otherwise, return False

        #Because later, when retrieving simulation time, we first need to check whether we're actually running inside a simulation.

        #The following method receives a log record.
    def filter(self, record: LogRecord) -> bool:
        """Attach information about simulation to log record."""
        
        if not hasattr(record, "sim_time"):
            #hasattr() checks whether an object has a particular attribute.

            #hasattr(record, "sim_time")
            #If this record does not already contain simulation time, add it.
            
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
        option = config.option

        if not option.log_format and config.getini("log_format") is DEFAULT_LOG_FORMAT:
            option.log_format = COCOTB_LOG_FORMAT

        create_log_record: Callable[..., LogRecord] = getLogRecordFactory()

        def log_record_factory(*args: object, **kwargs: object) -> LogRecord:
            record: LogRecord = create_log_record(*args, **kwargs)

            self._filter.filter(record)

            return record

        setLogRecordFactory(log_record_factory)

        if option.gpi_log_level:
            getLogger("gpi").setLevel(get_level(option.gpi_log_level))

        if option.cocotb_log_level:
            getLogger("cocotb").setLevel(get_level(option.cocotb_log_level))

    @hookimpl(tryfirst=True)
    def pytest_sessionstart(self, session: Session) -> None:
        """Called after the :py:class:`pytest.Session` object has been created and before performing collection and
        entering the run test loop.

        Args:
            session: The pytest session object.
        """
        config: Config = session.config
        plugin: LoggingPlugin | None = config.pluginmanager.get_plugin("logging-plugin")

        if plugin:
            plugin.log_file_handler.addFilter(self._filter)
            plugin.log_cli_handler.addFilter(self._filter)
            plugin.caplog_handler.addFilter(self._filter)
            plugin.report_handler.addFilter(self._filter)
