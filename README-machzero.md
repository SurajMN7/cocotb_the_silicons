# Main Issue to be solved
As mentioned in the open issue #5352 , given here: https://github.com/cocotb/cocotb/issues/5352 , When running pytest on two separate non-simulator requiring modules in the same python instance, an error is thrown as SimContextFilter in src/cocotb/_pytest/_logging cannot retrieve the simulation times. 

# Proposed Fix 1
We plan to introduce a pytest_sessionfinish hook to finish what the pytest_sessionstart hook started. During startup, cocotb uses it's own custom logging handlers and a LogRecord factory instead of Python's own. During teardown, all of cocotb's filters from all four handlers and safely restore the original LogRecord factory. That should not cause any more issues in regards to lingering filters or logs.

# Proposed Fix 2
