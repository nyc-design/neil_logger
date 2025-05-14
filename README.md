# Universal Logger

A reusable Python logger that logs to MongoDB and optionally to Sentry, with buffered flush, global error hooks, and function error decorators.

## Installation

### From GitHub (private repo):

```bash
pip install "git+https://github.com/nyc-design/universal-logger.git"

With Sentry support:
pip install "git+https://github.com/nyc-design/universal-logger.git#egg=universal-logger[sentry]"