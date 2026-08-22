"""Independent public schema versions.

Each published envelope evolves on its own.  A company-registry change must not
silently invalidate research, news, taxonomy, or release-manifest readers.
"""

RESEARCH_SCHEMA_VERSION = 1
COMPANY_SCHEMA_VERSION = 1
NEWS_SCHEMA_VERSION = 3
TAXONOMY_SCHEMA_VERSION = 1
RELEASE_SCHEMA_VERSION = 1
SEED_SCHEMA_VERSION = 1
