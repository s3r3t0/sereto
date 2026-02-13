import os
from unittest.mock import patch

import loguru
import pytest

from sereto.logging import (
    DEFAULT_LOG_LEVEL,
    LogConfig,
    LogLevel,
    _resolve_level,
    get_log_config,
    is_logging_configured,
    setup_logging,
)

# ---------------------------------------------------------------------------
# LogConfig
# ---------------------------------------------------------------------------


class TestLogConfig:
    @pytest.mark.parametrize("level", [LogLevel.DEBUG, LogLevel.TRACE])
    def test_show_exceptions_true(self, level):
        assert LogConfig(level=level).show_exceptions is True

    @pytest.mark.parametrize("level", [LogLevel.INFO, LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL])
    def test_show_exceptions_false(self, level):
        assert LogConfig(level=level).show_exceptions is False

    def test_show_locals_true_only_for_trace(self):
        assert LogConfig(level=LogLevel.TRACE).show_locals is True

    @pytest.mark.parametrize("level", [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARNING])
    def test_show_locals_false(self, level):
        assert LogConfig(level=level).show_locals is False


# ---------------------------------------------------------------------------
# _resolve_level
# ---------------------------------------------------------------------------


class TestResolveLevel:
    def test_explicit_level_takes_precedence(self):
        assert _resolve_level(LogLevel.WARNING) == LogLevel.WARNING

    def test_sereto_log_level_env_var(self):
        with patch.dict(os.environ, {"SERETO_LOG_LEVEL": "DEBUG"}, clear=False):
            assert _resolve_level(None) == LogLevel.DEBUG

    def test_sereto_log_level_env_var_case_insensitive(self):
        with patch.dict(os.environ, {"SERETO_LOG_LEVEL": "warning"}, clear=False):
            assert _resolve_level(None) == LogLevel.WARNING

    def test_invalid_sereto_log_level_falls_through(self):
        with patch.dict(os.environ, {"SERETO_LOG_LEVEL": "INVALID"}, clear=False):
            assert _resolve_level(None) == DEFAULT_LOG_LEVEL

    @pytest.mark.parametrize("debug_value", ["1", "true", "yes"])
    def test_debug_env_var(self, debug_value):
        env = {"DEBUG": debug_value}
        with patch.dict(os.environ, env, clear=False):
            # Remove SERETO_LOG_LEVEL if set
            os.environ.pop("SERETO_LOG_LEVEL", None)
            assert _resolve_level(None) == LogLevel.DEBUG

    def test_default_level(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SERETO_LOG_LEVEL", None)
            os.environ.pop("DEBUG", None)
            assert _resolve_level(None) == DEFAULT_LOG_LEVEL

    def test_explicit_overrides_env(self):
        with patch.dict(os.environ, {"SERETO_LOG_LEVEL": "ERROR"}, clear=False):
            assert _resolve_level(LogLevel.TRACE) == LogLevel.TRACE


# ---------------------------------------------------------------------------
# setup_logging & get_log_config (module-level singleton)
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def setup_method(self):
        """Reset module-level config before each test."""
        import sereto.logging as _mod

        self._mod = _mod
        self._original = _mod._current_config

    def teardown_method(self):
        """Restore original config after each test."""
        self._mod._current_config = self._original
        # Re-add a minimal handler so loguru doesn't break other tests
        loguru.logger.remove()
        loguru.logger.add(lambda msg: None, level="TRACE")

    def test_returns_log_config(self):
        config = setup_logging(LogLevel.WARNING)
        assert isinstance(config, LogConfig)
        assert config.level == LogLevel.WARNING

    def test_updates_module_singleton(self):
        setup_logging(LogLevel.ERROR)
        assert get_log_config().level == LogLevel.ERROR

    def test_get_log_config_default_before_setup(self):
        self._mod._current_config = None
        assert get_log_config().level == DEFAULT_LOG_LEVEL

    def test_successive_calls_update_config(self):
        setup_logging(LogLevel.DEBUG)
        assert get_log_config().level == LogLevel.DEBUG

        setup_logging(LogLevel.TRACE)
        assert get_log_config().level == LogLevel.TRACE

    def test_is_logging_configured_false_before_setup(self):
        self._mod._current_config = None
        assert is_logging_configured() is False

    def test_is_logging_configured_true_after_setup(self):
        self._mod._current_config = None
        setup_logging(LogLevel.INFO)
        assert is_logging_configured() is True

    def test_repl_log_level_survives_group_callback_reinvocation(self):
        """Regression: REPL `log TRACE` must not be overwritten when cli() re-runs with log_level=None."""
        # Simulate initial CLI startup
        setup_logging(LogLevel.INFO)
        assert get_log_config().level == LogLevel.INFO

        # Simulate `log TRACE` in REPL
        setup_logging(LogLevel.TRACE)
        assert get_log_config().level == LogLevel.TRACE

        # Simulate cli() group callback re-invocation (log_level=None, already configured)
        # The guard: `if log_level is not None or not is_logging_configured(): setup_logging(log_level)`
        if not is_logging_configured():
            setup_logging(None)

        # TRACE must be preserved
        assert get_log_config().level == LogLevel.TRACE
        assert get_log_config().show_exceptions is True
