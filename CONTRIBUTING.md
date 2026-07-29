# Contributing

Run `python -m compileall -q app` and `python -m pytest -q` before submitting a
pull request. Add regression coverage for any change to case state, audit
events, or redaction behavior. Never add a feature that sends a customer reply
without a separate, authenticated human-approval integration.
