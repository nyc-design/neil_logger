# Universal Logger

A reusable Python logger that logs to MongoDB and optionally to Sentry, with buffered flush, global error hooks, and function error decorators.

## Installation

### From GitHub (private repo):

```bash
pip install "git+https://<token>@github.com/<youruser>/universal-logger.git"

With Sentry support:
```bash
pip install "git+https://<token>@github.com/<youruser>/universal-logger.git#egg=universal-logger[sentry]"