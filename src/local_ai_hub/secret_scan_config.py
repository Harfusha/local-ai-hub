import re

_SECRET_SCAN_MAX_ENTRIES = 20_000
_SECRET_SCAN_MAX_FILES = 1_000
_SECRET_SCAN_MAX_FILE_BYTES = 1_048_576
_SECRET_SCAN_MAX_TOTAL_BYTES = 16_777_216
_SECRET_SCAN_MAX_LINE_BYTES = 65_536
_SECRET_SCAN_MAX_SECONDS = 5.0
_SECRET_SCAN_MAX_FINDINGS = 100

_SECRET_SCAN_PATTERNS: list[tuple[str, str, re.Pattern[str], str]] = [
    ("openai_api_key", "OpenAI API Key", re.compile(r"(sk-(?:proj-|live-)?[A-Za-z0-9_-]{20,60})"), "CRITICAL"),
    ("anthropic_api_key", "Anthropic API Key", re.compile(r"(sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{20,80})"), "CRITICAL"),
    ("aws_access_key", "AWS Access Key ID", re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "CRITICAL"),
    ("github_pat", "GitHub Personal Access Token", re.compile(r"\b((?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36})\b"), "CRITICAL"),
    ("slack_token", "Slack Token", re.compile(r"(xox[baprs]-[0-9A-Za-z-]{20,72})"), "HIGH"),
    ("slack_webhook", "Slack Incoming Webhook", re.compile(r"(https:\/\/hooks\.slack\.com\/services\/T[0-9A-Z]+\/B[0-9A-Z]+\/[0-9A-Za-z]+)"), "HIGH"),
    ("google_api_key", "Google Cloud / API Key", re.compile(r"\b(AIza[0-9A-Za-z-_]{35})\b"), "CRITICAL"),
    ("stripe_secret_key", "Stripe Secret Key", re.compile(r"\b((?:sk|rk)_(?:live|test)_[0-9a-zA-Z]{24,})\b"), "CRITICAL"),
    ("private_key", "Private Key Header", re.compile(r"(-----BEGIN (?:RSA|DSA|EC|OPENSSH|PGP) PRIVATE KEY-----)"), "CRITICAL"),
    ("db_connection_uri", "Database Connection URI with Password", re.compile(r"\b((?:postgres|postgresql|mysql|mongodb|redis):\/\/[a-zA-Z0-9_\-\.]+:[a-zA-Z0-9_\-\.@#$%^&*!]+@[a-zA-Z0-9_\-\.]+)"), "HIGH"),
    ("generic_secret_assignment", "Generic Hardcoded Secret", re.compile(r"(?:api_key|secret_key|auth_token|client_secret|access_token)\s*=\s*['\"]([A-Za-z0-9+/=_\-\.]{16,})['\"]", re.I), "HIGH"),
]
