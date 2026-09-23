"""Single source of truth for the running version: baked into the Docker image at build time
(the Dockerfile's VERSION build arg, set by CI from the git tag/branch, see CHANGELOG.md);
"dev" for a plain local `docker compose up --build` with no build arg passed."""
import os

VERSION = os.environ.get("APP_VERSION", "dev")
