# Cocotb Pytest Logging Cleanup – Investigation, Implementation and Testing

## Round 1: Picking the Repository and Choosing Our Issue

### Understanding the Issue

We selected the Cocotb repository and explored its open issues to identify a problem that we could investigate and work on.

The issue we chose was **[Issue #5352](https://github.com/cocotb/cocotb/issues/5352)**, which concerns cleaning up logging changes made by Cocotb after a pytest session finishes.

Cocotb wants every log message to include simulation-time information. To achieve this, it makes two changes to Python's logging system:

1. **Adds a simulation context filter:** Cocotb attaches its own filter to pytest's four logging handlers. This filter adds simulation-time information to log messages.
2. **Replaces the global LogRecordFactory:** Cocotb replaces Python's original logging record factory with a custom factory that applies Cocotb's logging changes whenever a new log record is created.

These modifications are necessary while a simulation is running. However, they should not remain active after the pytest session has ended.

If Cocotb does not undo its changes, its custom logging factory and filters might remain active and potentially affect subsequent tests or other plugins.

The expected behaviour is that Cocotb should clean up only the modifications it introduced:

- Restore Python's original logging factory.
- Remove its own filters from the four pytest logging handlers.
- Leave modifications made by other plugins untouched.

This gave us a clear problem to investigate: how Cocotb modifies the logging system, where those changes are made, and how they can be safely undone.

---

## Round 2: Investigation and Implementation

### 2.1 Understanding the Existing Logging Behaviour

Before making any changes, we examined how Cocotb interacts with Python's logging system when running inside a pytest environment.

We found that Cocotb does more than simply generate and display log messages. It modifies shared logging infrastructure to include simulation-specific information, such as simulation time and time units.

During our investigation, we identified two main areas where Cocotb modifies the existing logging infrastructure.

### Replacing the Global LogRecordFactory

Python provides two functions to access and modify its global logging record factory:

```python
getLogRecordFactory()
setLogRecordFactory()
```

The `LogRecordFactory` is responsible for creating the `LogRecord` objects used by Python's logging system.

Cocotb installs its own custom factory:

```python
setLogRecordFactory(log_record_factory)
```

The custom factory performs the following operations:

- Calls the previously active factory.
- Receives the newly created `LogRecord`.
- Applies Cocotb's simulation context filter.
- Returns the modified record.

This allows Cocotb to attach simulation-specific information to newly created log records.

**Why this matters:**

The logging factory is global. It is not restricted to Cocotb's logger or a particular pytest handler.

Other logging components running within the same Python process can also use it.

Consequently, if Cocotb finishes execution but leaves its custom factory installed, subsequent logging operations may continue using Cocotb's modified behaviour.

This creates a lifecycle issue: a modification intended for a particular testing session can affect logging operations beyond that session.

### Attaching Filters to Pytest Handlers

Cocotb also retrieves pytest's `LoggingPlugin`:

```python
plugin = config.pluginmanager.get_plugin("logging-plugin")
```

It attaches its simulation context filter to four handlers:

```python
plugin.log_file_handler.addFilter(self._filter)
plugin.log_cli_handler.addFilter(self._filter)
plugin.caplog_handler.addFilter(self._filter)
plugin.report_handler.addFilter(self._filter)
```

Each handler serves a different purpose:

| Handler | Purpose |
|---|---|
| `log_file_handler` | Writes logs to a file |
| `log_cli_handler` | Displays logs in the terminal |
| `caplog_handler` | Captures logs for tests |
| `report_handler` | Captures logs associated with pytest reports |

The filter is attached to all four handlers so that simulation metadata is available through the different logging destinations.

However, these handlers belong to pytest's logging infrastructure. Cocotb attaches its filter to them but does not own the handlers themselves.

**Important distinction:** Cocotb owns the filter it introduces, but pytest owns the handlers. 

This distinction influenced our implementation. We needed to remove Cocotb's filter without closing, replacing, or interfering with pytest's handlers or other plugins' filters.

### 2.2 Investigation and Design Considerations

Before implementing the cleanup mechanism, we examined the ownership and lifecycle of the objects involved.

Our investigation focused on understanding:

- Which components created the logging objects.
- Which components modified them.
- Which components were responsible for managing their lifecycle.
- When those modifications should be undone.
- How to avoid interfering with other plugins.

#### Understanding the Logging Factory's Lifecycle

Python provides the original logging factory, which Cocotb retrieves using:

```python
getLogRecordFactory()
```

Cocotb then installs a wrapper around this factory.

We identified that the original factory needed to be preserved before Cocotb replaced it.

Without retaining a reference to the previous factory, Cocotb would not have a reliable way to restore the original logging behaviour after the session.

#### Understanding Handler Ownership

The four logging handlers are provided by pytest's `LoggingPlugin`.

Cocotb does not create these handlers. It only attaches its own filter to them.

Therefore, the appropriate cleanup operation is:

```python
handler.removeFilter(self._filter)
```

Closing or removing the entire handler would be inappropriate because pytest is responsible for managing its own logging resources.

Our implementation therefore focuses on removing only the filter introduced by Cocotb.

#### Choosing the Cleanup Point

We examined the pytest plugin lifecycle to determine when Cocotb should reverse its logging modifications.

We chose the `pytest_sessionfinish` hook:

```python
pytest_sessionfinish
```

This provides an appropriate point to perform cleanup after the test session has finished.

We also examined pytest's own teardown behaviour. Its `LoggingPlugin` has a separate `pytest_unconfigure` implementation that explicitly closes its log file handler.

This helped establish an important separation of responsibilities:

- Cocotb should undo the modifications it introduced.
- Pytest should manage the lifecycle of its own logging handlers.

#### Handling Changes Made by Other Plugins

One important edge case we considered was the possibility of another plugin modifying the global logging factory after Cocotb had installed its own.

Consider the following sequence:

1. Python starts with factory A.
2. Cocotb installs factory B, which wraps factory A.
3. Another plugin installs factory C, which wraps factory B.
4. Cocotb's pytest session finishes.

If Cocotb blindly restores factory A, it would overwrite factory C, destroying another plugin's modification.

We considered this unsafe because the global logging state may be shared by multiple components.

This led us to adopt a central design principle:

**Cocotb should restore only the modifications it can identify as its own, without overwriting changes made by other components.**

### 2.3 Implementation Changes

Based on our investigation, we introduced changes to preserve the original logging state, track the objects modified by Cocotb, and clean up those modifications after the pytest session.

#### Preserving the Original LogRecordFactory

Previously, the implementation retrieved the currently active factory into a local variable:

```python
create_log_record: Callable[..., LogRecord] = getLogRecordFactory()
```

Although this allowed Cocotb to wrap the existing factory, the original factory was not retained as an instance attribute for later restoration.

We changed this to:

```python
self._original_log_record_factory: Callable[..., LogRecord] = (
    getLogRecordFactory()
)
```

This stores the factory that was active before Cocotb modifies it.

We then use this saved reference when creating the wrapper:

```python
create_log_record: Callable[..., LogRecord] = (
    self._original_log_record_factory
)
```

This ensures that Cocotb continues to preserve the behaviour of the previously installed factory.

Retaining the original factory also makes it accessible during the cleanup phase, even after initialization has completed.

#### Retaining a Reference to Cocotb's Custom Factory

The original implementation created and installed the custom factory directly:

```python
setLogRecordFactory(log_record_factory)
```

However, the implementation did not retain a reference to that exact function for later comparison.

We modified this to:

```python
self._log_record_factory = log_record_factory
setLogRecordFactory(self._log_record_factory)
```

Keeping this reference allows Cocotb to identify whether its custom factory is still installed when cleanup takes place.

This is important when other plugins may have modified the global factory in the meantime.

#### Tracking the Pytest Logging Handlers

Previously, Cocotb attached its filter directly to each pytest handler:

```python
plugin.log_file_handler.addFilter(self._filter)
plugin.log_cli_handler.addFilter(self._filter)
plugin.caplog_handler.addFilter(self._filter)
plugin.report_handler.addFilter(self._filter)
```

The filter was attached successfully, but the implementation did not maintain a collection of the handlers that received it.

We introduced a list to retain those references:

```python
self._handlers: list[logging.Handler] = []
```

During `pytest_sessionstart`, we populate this list:

```python
self._handlers = [
    plugin.log_file_handler,
    plugin.log_cli_handler,
    plugin.caplog_handler,
    plugin.report_handler,
]
```

We then attach the filter using a loop:

```python
for handler in self._handlers:
    handler.addFilter(self._filter)
```

This change allows Cocotb to retain the exact handler objects it modified.

Instead of attempting to locate the handlers again during cleanup, it can directly use the saved references.

It also makes the attachment and removal operations consistent.

#### Restoring the Original Factory Conditionally

We introduced a new `pytest_sessionfinish` method to handle cleanup after the session.

The factory restoration logic is:

```python
if getLogRecordFactory() is self._log_record_factory:
    setLogRecordFactory(self._original_log_record_factory)
```

This performs an identity check before restoring the original factory.

The operations involved are:

- `getLogRecordFactory()` retrieves the factory currently installed in Python's logging system.
- `is self._log_record_factory` checks whether the currently installed factory is the exact same function object that Cocotb installed.
- `setLogRecordFactory(self._original_log_record_factory)` restores the factory that existed before Cocotb made its modification.

The identity check is important because comparing only function names or behaviour would not reliably establish ownership.

If another component has replaced Cocotb's factory, the condition prevents Cocotb from overwriting that component's change.

This makes restoration conditional rather than unconditional.

#### Removing Only Cocotb's Filter

The second cleanup operation in `pytest_sessionfinish` is:

```python
for handler in self._handlers:
    handler.removeFilter(self._filter)
```

This removes the exact filter instance that Cocotb attached during session startup.

It does not:

- Remove filters belonging to other plugins.
- Close pytest's logging handlers.
- Replace pytest's logging configuration.
- Clear the entire logging system.

Since the handlers belong to pytest, removing only Cocotb's filter ensures that their existing configuration and ownership remain intact.

### 2.4 Overall Logging Lifecycle After the Changes

With these changes, Cocotb's logging lifecycle becomes:

**Initialization**

- Create the simulation context filter.
- Save the currently active logging factory.
- Create the custom factory that wraps the original factory.
- Retain a reference to the custom factory.

**Factory Installation**

- Install Cocotb's custom factory.
- Newly created log records receive simulation context information.

**Pytest Session Startup**

- Retrieve pytest's logging handlers.
- Store references to all four handlers.
- Attach Cocotb's filter to each handler.

**Simulation and Test Execution**

- Log records are created through the custom factory.
- Simulation metadata is attached to the records.
- Pytest's handlers process the records through their respective logging destinations.

**Session Completion**

- Check whether Cocotb's custom factory is still installed.
- Restore the original factory only if Cocotb's factory is still active.
- Remove Cocotb's filter from all tracked handlers.

**Intended Final State**

The logging modifications introduced by Cocotb are undone, while unrelated logging configuration and modifications made by other components are left untouched.

---

## Round 3: Testing, Validation and Edge Cases

A new test file, tests/pytest_plugin/tests_logging_cleanup.py, has been added to verify logging cleanup. Run this test file first, followed by the main test_plugin test suite to ensure the logging cleanup issue is addressed before executing the remaining tests.

### 3.1 Testbench Overview

The testbench verifies whether Cocotb correctly cleans up the changes it makes to Python's logging system after a pytest session finishes.

It focuses on two main components:

- **LogRecordFactory:** Cocotb replaces Python's global logging factory to add simulation-time information to log records.
- **Logging Filters:** Cocotb attaches its simulation context filter to pytest's four logging handlers.

To test the cleanup functionality independently, a `Logging` plugin object is created using:

```python
Logging.__new__()
```

This creates an instance without calling its normal constructor. The required attributes, such as the original factory, Cocotb's custom factory, filters, and handlers, are assigned manually.

Different logging situations are then simulated by installing custom factories and attaching filters to logging handlers.

The `pytest_sessionfinish()` hook is called to trigger cleanup, and Python `assert` statements are used to verify whether the expected changes have taken place.

This approach allows us to test the cleanup mechanism directly without needing to run a complete simulation.

### 3.2 Test Cases

#### 1. `test_logging_restores_original_factory()`

**Purpose:** Verify that Cocotb restores Python's original logging factory after the pytest session ends.

**Test procedure:**

1. Save the original logging factory.
2. Install a custom factory representing Cocotb's factory.
3. Call the `pytest_sessionfinish()` cleanup hook.
4. Check whether the original factory has been restored.

**Expected result:** The original factory should be active after cleanup.

#### 2. `test_logging_removes_own_filter_only()`

**Purpose:** Verify that Cocotb removes only its own filter while leaving other plugins' filters untouched.

**Test procedure:**

1. Create a logging handler.
2. Attach Cocotb's filter to the handler.
3. Attach another filter representing a different plugin.
4. Call the cleanup hook.
5. Check which filters remain attached.

**Expected result:** Cocotb's filter should be removed, while the other plugin's filter should remain attached.

#### 3. `test_logging_does_not_overwrite_another_factory()`

**Purpose:** Verify that Cocotb does not overwrite changes made to the global logging factory by another plugin.

**Test procedure:**

1. Install Cocotb's custom factory.
2. Install another plugin's factory, replacing Cocotb's factory.
3. Call Cocotb's cleanup hook.
4. Check which factory is currently active.

**Expected result:** The other plugin's factory should remain active. Cocotb should not overwrite another component's modification.

#### 4. `test_logging_removes_filter_from_all_four_handlers()`

**Purpose:** Verify that Cocotb removes its filter from all four pytest logging handlers.

**Test procedure:**

1. Create or obtain the four logging handlers.
2. Attach Cocotb's filter to each handler.
3. Call the cleanup hook.
4. Check each handler to verify whether Cocotb's filter is still attached.

**Expected result:** Cocotb's filter should be removed from all four handlers.

### 3.3 What These Tests Establish

Together, these four tests validate the main cleanup requirements of Issue #5352:

| Requirement | Test |
|---|---|
| Restore the original logging factory | `test_logging_restores_original_factory()` |
| Remove only Cocotb's filter | `test_logging_removes_own_filter_only()` |
| Preserve another plugin's factory | `test_logging_does_not_overwrite_another_factory()` |
| Remove the filter from all four handlers | `test_logging_removes_filter_from_all_four_handlers()` |

The tests specifically check both normal cleanup behaviour and situations where other plugins have modified the shared logging infrastructure.

This is important because simply checking that Cocotb's changes disappear is insufficient. We must also ensure that cleanup does not accidentally remove or overwrite changes belonging to other components.

### 3.4 Regression Testing

In addition to the cleanup-specific tests, the existing pytest plugin test suite was executed using:

```bash
pytest -v tests/pytest_plugin
```

The test run reported:

```text
98 passed, 7 skipped, 20 xfailed
```

The Cocotb runner also reported:

```text
8 passed
```

These results indicate that the existing pytest plugin tests and runner tests completed successfully, with the reported skips and expected failures.

**Validation conclusion:**

The cleanup-specific tests verify the intended behaviour of the new implementation, while the existing regression tests help ensure that the changes do not break Cocotb's existing pytest functionality.

Together, they provide validation at both the implementation level and the broader regression level.

### 3.5 Edge Cases and How We Handle Them

Apart from testing the normal cleanup behaviour, we considered situations where the logging system might have been modified by other components or where cleanup could behave unexpectedly.

The objective was to ensure that Cocotb's cleanup remains safe even when the logging environment is not in its original state.

#### 1. Another Plugin Replaces Cocotb's Logging Factory

**Scenario:**

Cocotb installs its custom logging factory, but another plugin replaces it before the pytest session finishes.

**Potential problem:**

If Cocotb blindly restores the original factory, it could overwrite the other plugin's modification.

**How we handle it:**

We use an identity check:

```python
if getLogRecordFactory() is self._log_record_factory:
    setLogRecordFactory(self._original_log_record_factory)
```

Cocotb restores the original factory only if its own factory is still active.

If another plugin has replaced it, Cocotb leaves the current factory untouched.

**Test coverage:** `test_logging_does_not_overwrite_another_factory()`

#### 2. Other Plugins Have Their Own Filters on the Same Handler

**Scenario:**

Another plugin attaches its own filter to a pytest logging handler alongside Cocotb's filter.

**Potential problem:**

Removing all filters during cleanup could accidentally remove filters belonging to other plugins.

**How we handle it:**

Instead of clearing the handler's filters, we remove only Cocotb's specific filter instance:

```python
handler.removeFilter(self._filter)
```

This preserves filters installed by other components.

**Test coverage:** `test_logging_removes_own_filter_only()`

#### 3. Cocotb Must Clean Up All Four Handlers

**Scenario:**

Cocotb attaches its filter to four different pytest logging handlers. If cleanup removes the filter from only some of them, the remaining handlers could continue applying Cocotb's simulation context filter.

**Potential problem:**

Leftover filters could cause inconsistent logging behaviour after the session finishes.

**How we handle it:**

We maintain references to all four handlers in a list:

```python
self._handlers = [
    plugin.log_file_handler,
    plugin.log_cli_handler,
    plugin.caplog_handler,
    plugin.report_handler,
]
```

Cleanup iterates through every tracked handler:

```python
for handler in self._handlers:
    handler.removeFilter(self._filter)
```

This ensures that the cleanup operation is applied consistently to all four handlers.

**Test coverage:** `test_logging_removes_filter_from_all_four_handlers()`

#### 4. The Original Factory Must Be Preserved Correctly

**Scenario:**

Cocotb replaces the global factory but does not retain the factory that was active before its modification.

**Potential problem:**

Without the original factory reference, Cocotb would not know which factory to restore after the session.

**How we handle it:**

We save the original factory before installing Cocotb's custom factory:

```python
self._original_log_record_factory = getLogRecordFactory()
```

We retain this reference throughout the plugin's lifecycle and use it during cleanup.

This ensures that the previous logging behaviour can be restored.

**Test coverage:** `test_logging_restores_original_factory()`

#### 5. Cleanup Must Not Interfere With Pytest's Handlers

**Scenario:**

Cocotb uses handlers owned and managed by pytest.

**Potential problem:**

Closing or replacing these handlers during Cocotb's cleanup could interfere with pytest's own logging lifecycle.

**How we handle it:**

We do not close, replace, or remove the handlers themselves.

We only remove the filter that Cocotb attached:

```python
handler.removeFilter(self._filter)
```

Pytest remains responsible for managing its own handlers and resources.

**Validation approach:** Verify that the handlers remain intact after cleanup and that only Cocotb's filter is removed.

#### 6. Cleanup When Cocotb's Factory Is No Longer Active

**Scenario:**

By the time `pytest_sessionfinish()` executes, the currently installed factory is no longer Cocotb's factory.

**Potential problem:**

Unconditional restoration could overwrite a modification made by another component.

**How we handle it:**

The identity check ensures that restoration happens only when Cocotb's custom factory is still installed.

If the condition is false, the factory is left unchanged.

This is an important ownership safeguard.

### 3.6 Edge Case Handling Summary

| Edge case | Protection |
|---|---|
| Another plugin replaces the factory | Conditional identity check |
| Other plugins attach their own filters | Remove only Cocotb's filter |
| Filter remains on one of the four handlers | Track and iterate through all four handlers |
| Original factory is needed during cleanup | Preserve it as an instance attribute |
| Pytest owns the logging handlers | Never close or replace pytest's handlers |
| Cocotb's factory is no longer active | Skip factory restoration |

**Overall takeaway:**

Our approach is not simply to reverse logging changes. It is to reverse them safely while respecting shared ownership of Python's logging infrastructure.

The key principle is:

**Clean up what Cocotb owns, preserve what other components own, and avoid disturbing the logging system beyond the changes introduced by Cocotb.**

---

## Conclusion

The main objective of this implementation was to make Cocotb's pytest logging modifications properly manageable across the lifetime of a test session.

The existing implementation already provided simulation-aware logging by wrapping Python's global `LogRecordFactory` and attaching a simulation context filter to pytest's logging handlers.

Our changes focused on the missing cleanup mechanism.

We:

- Preserved the original logging factory.
- Retained a reference to the custom factory installed by Cocotb.
- Tracked the four pytest handlers that received Cocotb's filter.
- Introduced session-finish cleanup to reverse these modifications.
- Used an identity check to avoid overwriting logging changes made by other plugins.
- Removed only Cocotb's filter instead of interfering with pytest's handlers or unrelated filters.
- Added cleanup-specific tests to validate the expected behaviour.
- Considered edge cases involving shared logging state and plugin ownership.

The most important design decision throughout the implementation was to avoid resetting the entire logging system.

Instead, cleanup is limited to the specific objects and modifications introduced by Cocotb.

**In essence, the implementation follows this sequence:**

**Preserve the original state → Install Cocotb's modifications → Execute the pytest session → Remove Cocotb's filter → Conditionally restore the original factory.**
