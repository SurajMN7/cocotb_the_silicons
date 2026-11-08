import logging

from cocotb_tools._pytest._logging import Logging


def test_logging_restores_original_factory():
    original_factory = logging.getLogRecordFactory()

    def custom_factory(*args, **kwargs):
        return original_factory(*args, **kwargs)

    plugin = Logging.__new__(Logging)

    plugin._original_log_record_factory = original_factory
    plugin._log_record_factory = custom_factory
    plugin._filter = logging.Filter()
    plugin._handlers = []

    logging.setLogRecordFactory(custom_factory)

    try:
        plugin.pytest_sessionfinish(None, 0)

        assert logging.getLogRecordFactory() is original_factory

    finally:
        logging.setLogRecordFactory(original_factory)

def test_logging_removes_own_filter_only():
    handler = logging.StreamHandler()

    cocotb_filter = logging.Filter()
    other_filter = logging.Filter()

    handler.addFilter(cocotb_filter)
    handler.addFilter(other_filter)

    plugin = Logging.__new__(Logging)
    plugin._filter = cocotb_filter
    plugin._handlers = [handler]

    original_factory = logging.getLogRecordFactory()
    plugin._original_log_record_factory = original_factory
    plugin._log_record_factory = original_factory

    plugin.pytest_sessionfinish(None, 0)

    assert cocotb_filter not in handler.filters
    assert other_filter in handler.filters

def test_logging_does_not_overwrite_another_factory():
    original_factory = logging.getLogRecordFactory()

    def cocotb_factory(*args, **kwargs):
        return original_factory(*args, **kwargs)

    def another_plugin_factory(*args, **kwargs):
        return original_factory(*args, **kwargs)

    plugin = Logging.__new__(Logging)
    plugin._original_log_record_factory = original_factory
    plugin._log_record_factory = cocotb_factory
    plugin._filter = logging.Filter()
    plugin._handlers = []

    logging.setLogRecordFactory(another_plugin_factory)

    try:
        plugin.pytest_sessionfinish(None, 0)

        assert logging.getLogRecordFactory() is another_plugin_factory

    finally:
        logging.setLogRecordFactory(original_factory)
from unittest.mock import Mock


def test_logging_removes_filter_from_all_four_handlers():
    handlers = [logging.StreamHandler() for _ in range(4)]

    plugin = Logging.__new__(Logging)
    plugin._filter = logging.Filter()
    plugin._handlers = handlers

    original_factory = logging.getLogRecordFactory()
    plugin._original_log_record_factory = original_factory
    plugin._log_record_factory = original_factory

    for handler in handlers:
        handler.addFilter(plugin._filter)

    plugin.pytest_sessionfinish(None, 0)

    for handler in handlers:
        assert plugin._filter not in handler.filters
