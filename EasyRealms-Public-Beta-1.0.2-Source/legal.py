"""Legal text and versioned first-run acceptance for Easy Realms."""
from __future__ import annotations

from datetime import datetime, timezone


APP_VERSION = "Public Beta 1.0.2"
AGREEMENT_VERSION = "2026-11-17-v1"
DISCLAIMER = (
    "NOT AN OFFICIAL MINECRAFT PRODUCT. NOT APPROVED BY OR ASSOCIATED WITH "
    "MOJANG OR MICROSOFT."
)

AGREEMENT_HTML = f"""
<h2>Easy Realms End User Agreement</h2>
<p><b>{DISCLAIMER}</b></p>
<p>Easy Realms is an independent community tool for creating and managing
Minecraft servers on a computer you control.</p>

<h3>Your responsibilities</h3>
<ul>
  <li>You must follow the Minecraft EULA and Usage Guidelines, applicable laws,
      and the licences of server software, mods and plugins you install.</li>
  <li>You are responsible for the people you invite, the files you install,
      your server content and any network access you enable.</li>
  <li>Only grant operator access to people you trust. Use an allow-list before
      sharing a server publicly.</li>
</ul>

<h3>Downloads and external services</h3>
<p>Easy Realms downloads server software and metadata from third-party providers
such as Mojang/Microsoft, PaperMC, Fabric, Modrinth, Eclipse Adoptium and Playit.
Those providers are separate from Easy Realms and may apply their own terms and
privacy policies. Easy Realms does not sell or redistribute Minecraft itself.</p>

<h3>Network sharing</h3>
<p>Making a server reachable from the internet has risks. Easy Realms recommends
Playit so friends receive a tunnel address instead of your home IP address.
Direct router forwarding is an advanced, opt-in fallback. Keep online mode and
the player allow-list enabled, keep software updated, and never share passwords,
claim links, private keys or account recovery codes.</p>

<h3>Local data, backups and warranty</h3>
<p>Easy Realms stores its settings, logs, downloaded runtimes and managed server
information locally in its data folder. It does not automatically upload your
worlds or diagnostic logs. Keep independent backups of important worlds.</p>
<p>This public beta software is provided without a guarantee that it will be
uninterrupted, error-free or suitable for every computer, router, mod or world.
To the extent permitted by law, you use it at your own risk. Nothing here
excludes rights that cannot legally be excluded.</p>

<p>By selecting <b>I agree</b>, you confirm that you have read and accepted this
agreement. Agreement revision: {AGREEMENT_VERSION}.</p>
"""


def agreement_is_current(settings) -> bool:
    """Return whether *settings* records acceptance of the current revision."""
    return str(settings.value("legal/agreement_version", "")) == AGREEMENT_VERSION


def record_acceptance(settings, accepted_at: str | None = None) -> None:
    """Record acceptance without storing a name, account or other identity."""
    timestamp = accepted_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    settings.setValue("legal/agreement_version", AGREEMENT_VERSION)
    settings.setValue("legal/accepted_at_utc", timestamp)
    settings.sync()

