"""
logger_setup — Provides a flexible and reusable logger configuration system for CLI tools, enabling structured logging with multiple log levels and file handlers, ensuring consistent logging behavior across applicat

### PART-META-JSON
{
  "name": "logger_setup",
  "layer": "clitools",
  "purpose": "Provides a flexible and reusable logger configuration system for CLI tools, enabling structured logging with multiple log levels and file handlers, ensuring consistent logging behavior across applicat",
  "addition": true,
  "status": "core",
  "dependencies": [],
  "inputs": "Public API: setup_logger(config); LoggerConfig(...).",
  "outputs": "Returns: setup_logger -> logging.Logger.",
  "files_created": [],
  "security_notes": "Touches the local filesystem; validate paths to prevent traversal outside the intended root.",
  "ai_usage": "Import what you need from `scrapyard.clitools.logger_setup`.",
  "example": "from scrapyard.clitools.logger_setup import *",
  "import_path": "scrapyard.clitools.logger_setup"
}
### END-PART-META
"""
import os
import logging
import logging.handlers

class LoggerConfig:
    def __init__(self, log_level: str, file_path: str, max_bytes: int, backup_count: int):
        self.log_level = log_level
        self.file_path = file_path
        self.max_bytes = max_bytes
        self.backup_count = backup_count

def setup_logger(config: LoggerConfig) -> logging.Logger:
    logger = logging.getLogger('scrapyard')
    logger.setLevel(getattr(logging, config.log_level.upper()))

    # Ensure the logger does not have existing handlers to avoid duplication
    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            filename=config.file_path,
            maxBytes=config.max_bytes,
            backupCount=config.backup_count
        )
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

def _selftest():
    import tempfile
    from contextlib import ExitStack

    with ExitStack() as stack:
        temp_dir = stack.enter_context(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        log_file_path = os.path.join(temp_dir, 'test.log')

        config = LoggerConfig(log_level='DEBUG', file_path=log_file_path, max_bytes=1024, backup_count=3)

        logger = setup_logger(config)
        logger.debug('This is a debug message')
        logger.info('This is an info message')
        logger.warning('This is a warning message')
        logger.error('This is an error message')
        logger.critical('This is a critical message')

        # Ensure the log file was created
        assert os.path.exists(log_file_path), "Log file was not created"

        with open(log_file_path, 'r') as f:
            log_content = f.read()

        # Check that all log levels are present
        assert 'DEBUG' in log_content, "DEBUG level not found in log"
        assert 'INFO' in log_content, "INFO level not found in log"
        assert 'WARNING' in log_content, "WARNING level not found in log"
        assert 'ERROR' in log_content, "ERROR level not found in log"
        assert 'CRITICAL' in log_content, "CRITICAL level not found in log"

        # Ensure the logger level is set correctly
        assert logger.getEffectiveLevel() == logging.DEBUG, "Logger level is not set to DEBUG"

    print("Selftest completed successfully.")

if __name__ == "__main__":
    _selftest()
