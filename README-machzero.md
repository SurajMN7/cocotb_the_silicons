# Main Issue to be solved
As mentioned in the open issue #5352 , given here: https://github.com/cocotb/cocotb/issues/5352 , When running pytest on two separate non-simulator requiring modules in the same python instance, an error is thrown as SimContextFilter in src/cocotb/_pytest/_logging cannot retrieve the simulation times. 

# Proposed Fix 1
We plan to introduce a pytest_sessionfinish hook to finish what the pytest_sessionstart hook started. During startup, cocotb uses it's own custom logging handlers and a LogRecord factory instead of Python's own. During teardown, all of cocotb's filters from all four handlers and safely restore the original LogRecord factory. That should not cause any more issues in regards to lingering filters or logs.

# Proposed Fix 2
We planned to make changes to file named _logging which involve :
      1) Restoring cocotb's global factory modfifications removing
      2) Remove Cocotb's handler-level filters
      3) Preserve logging changes belonging to other components
      4) Avoid interfering with the existing regression logging management


self._original_log_record_factory = getLogRecordFactory()

self._log_record_factory = log_record_factorysetLogRecordFactory(self._log_record_factory)

if getLogRecordFactory() is self._log_record_factory:    setLogRecordFactory(self._original_log_record_factory)

for handler in self._handlers:    handler.removeFilter(self._filter)


# TestCases
Test cases tested for in (tests_logging_cleanup.py) file:
1) Check if original factory is restored after session as if not can cause errors to other plugins.
2) Checking if cocotb only removes it own filters not any other filters belonging to other plugins.
3) Checks if Cocotb removes its filter from all four logging handlers.
4) Checks if Cocotb leaves another plugin's factory alone if that plugin has changed it.
