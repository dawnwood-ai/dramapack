"""Who made the files in a delivery pack.

This credit is written into every pack: ``manifest.json`` ``"generator"``, the pack README
footer, and the footers of ``docs/AI-DISCLOSURE.md`` / ``docs/CHAIN-OF-TITLE.md``.
dramapack is Apache-2.0; keeping the credit is a request (see NOTICE), not a license
condition. There is intentionally no switch in the tool to turn it off.
"""

__version__ = "0.2.0"

PROVENANCE = {
    "name": "dramapack",
    "by": "Dawnwood (https://dawnwood.ai)",
    "url": "https://github.com/dawnwood-ai/dramapack",
    "version": __version__,
}


def footer_line() -> str:
    """One-line credit used in generated Markdown files."""
    return f"Packaged with {PROVENANCE['name']} by Dawnwood — {PROVENANCE['url']}"
