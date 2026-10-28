import re
import json

class LogSanitizer:
    def __init__(self):
        # Define regex patterns for common sensitive data
        self.patterns = {
            "api_key": r"(api[_-]?key|secret|token|auth)[=:\s]+['\"]?([a-zA-Z0-9_\-]{20,})['\"]?",
            "bearer_token": r"Bearer\s+[a-zA-Z0-9_\-\.]+",
            "ip_address": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
            "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "password": r"(password|passwd|pwd)[=:\s]+['\"]?([^\s'\"]+)['\"]?"
        }

    def sanitize(self, log_text: str) -> str:
        """Scrub sensitive data from log text using local regex patterns."""
        sanitized_text = log_text

        # Replace API keys, tokens, and passwords
        sanitized_text = re.sub(self.patterns["api_key"], r"\1=[REDACTED]", sanitized_text, flags=re.IGNORECASE)
        sanitized_text = re.sub(self.patterns["bearer_token"], "Bearer [REDACTED]", sanitized_text, flags=re.IGNORECASE)
        sanitized_text = re.sub(self.patterns["password"], r"\1=[REDACTED]", sanitized_text, flags=re.IGNORECASE)
        
        # Scrub emails and IPs for high privacy
        sanitized_text = re.sub(self.patterns["email"], "[EMAIL_REDACTED]", sanitized_text)
        sanitized_text = re.sub(self.patterns["ip_address"], "[IP_REDACTED]", sanitized_text)
        
        return sanitized_text


class LogParser:
    @staticmethod
    def parse_log(raw_line: str):
        """Attempts to parse a log line as JSON, otherwise treats it as a raw string/stack trace."""
        try:
            return json.loads(raw_line)
        except json.JSONDecodeError:
            return {"raw_message": raw_line.strip()}


if __name__ == "__main__":
    sanitizer = LogSanitizer()
    
    # Mock messy/sensitive log sample containing secrets, passwords, and IPs
    sample_log = '2026-10-28 14:00:00 ERROR Database connection failed for user=admin password=SuperSecret123 using API_KEY=sk-proj-abcdef1234567890abcdef from IP 192.168.1.50 contact admin@example.com'
    
    print("=== BEFORE SANITIZATION ===")
    print(sample_log)
    
    clean_log = sanitizer.sanitize(sample_log)
    
    print("\n=== AFTER LOCAL SANITIZATION ===")
    print(clean_log)
