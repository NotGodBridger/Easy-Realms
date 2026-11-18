# Easy Realms — Public Beta 1.0.2

> **NOT AN OFFICIAL MINECRAFT PRODUCT. NOT APPROVED BY OR ASSOCIATED WITH MOJANG OR MICROSOFT.**

Easy Realms is an independent community tool. The first launch requires review
and acceptance of the Easy Realms End User Agreement. Acceptance is stored only
in the local `data/settings.ini` file and can be reviewed from **About & legal**.

## Windows portable launch

The Windows development distribution is a portable ZIP. Right-click the ZIP,
choose **Extract All**, open the extracted folder, and run `START HERE.cmd`.
Keep it beside the complete visible `data` folder. The private Python/Qt runtime
is already included and no application dependency is downloaded.

The portable launcher is unsigned and may still receive a Windows reputation
warning. Do not disable Windows Defender to run Easy Realms.

`START HERE.cmd` creates `data/logs` first, records its pre-launch checks, checks
that `pythonw.exe`, `python313.dll`, the Microsoft runtime, Qt and the app are
present, then starts the bundled runtime directly. If it says files are missing,
extract a fresh copy of the complete ZIP. Worlds, settings, backups and downloads
remain in `data`.

## Data layout

- `data/app/`: application and assets.
- `data/runtime/`: private Python and interface runtime.
- `data/java/<major>/`: private Java runtimes downloaded as needed.
- `data/servers/`: default location for newly created Minecraft servers.
- `data/backups/`: backups created from My servers.
- `data/servers.json`: the local server library. Removing an entry does not delete its files.
- `data/settings.ini`: saved Java selection and Paper contact preference.
- `data/logs/`: one timestamped diagnostic file per launch, plus launcher or
  setup logs when startup fails. The app marks clean exits, retains incomplete
  crash logs and automatically keeps only the 30 newest launch logs. Use
  **About & legal → Open diagnostic logs** to open this folder.
- `data/app.log` and `data/app-error.log`: low-level fallback output written by
  the current portable launcher if Python fails before the diagnostic system
  can start.

Existing server folders are not moved or overwritten. Use Import server to add one to My servers. Easy Realms adds only its small management file when needed. Internal `easyservers.json` metadata remains compatible. The previous EasyServers settings are migrated where the new settings do not already exist.

## Java and server creation

Select Vanilla, Fabric, Paper or Bedrock and a supported Minecraft release. Set Java runtime to **Automatic** for Java Edition servers to try Java on PATH, then a previously downloaded runtime, then download the matching Windows or Linux x64 Temurin JRE into `data/java`. Published Java server checksums are verified. Bedrock uses Microsoft’s native 64-bit Windows server and does not need Java; Easy Realms downloads the current stable and Preview builds offered on minecraft.net, validates the ZIP structure, and keeps Preview worlds clearly separated by the server name you choose.

Select a name, RAM amount and destination folder, read and accept the Minecraft EULA, and create your server. Paper requires a public contact URL or email for its download API. My servers provides launch access, edition-aware properties, safe Java/Bedrock imports and recoverable backups. Launch, graceful Restart and Stop are on the Console tab. Type commands in the command box; Enter/Send submits and Up/Down recalls recent commands. Play with friends contains separate Java and current Bedrock NetherNet playit.gg guidance.

The Console tab also shows live CPU usage, resident memory, uptime and the most recently reported player count for the running server. A short status message translates sustained CPU or memory pressure into plain language. Monitoring uses Windows process information directly and adds no third-party runtime dependency.

Server Doctor performs read-only checks for missing or invalid server files, unsafe configured paths, Java availability, port and memory settings, storage space, account authentication, allow-lists and internet-sharing choices. Launch is blocked only for problems that would prevent the server starting safely; recommendations remain visible in Manage and Console. Reports can be copied for public beta bug reports.

Fabric and Paper servers include a Modrinth browser filtered to the selected Minecraft version and loader. Easy Realms downloads only from Modrinth's HTTPS CDN, verifies the published hash, installs required dependencies, and records the files it owns so updates and removal do not touch manually installed add-ons. The install preview warns when players also need matching client mods. Fabric includes Performance essentials and Simple Voice Chat presets. Voice chat still needs the mod on each participating client and a separate UDP tunnel; the Play with friends tab explains the recommended playit setup.

The interface keeps creation and server management separate. The sidebar uses a
Server software dropdown for Vanilla, Fabric, Paper and Bedrock, plus a Library
dropdown for My servers, imports, the change log and legal information. The main
bar contains My servers, Create, Manage, Console, Players, Add-ons and Share.
Manage divides settings, Server Doctor and backups into focused sections, while
rare library actions live under each server card's More menu. Add-on browsing and
installed add-ons are also separated so smaller screens remain usable.

Public Beta 1.0.2 keeps the selected server and its live state in a compact
title-row control, with Ready/Selected/Running badges in My servers and clear
tooltips for unavailable tabs. The Create page focuses on the version selector,
one live compatibility line and the main Continue action instead of surrounding
the workflow with instructional boxes. Import server is available directly from
the same page, and an empty library offers clear Create and Import actions.

About & legal can export a local, privacy-scrubbed bug report ZIP containing
basic runtime details, up to five recent Easy Realms diagnostics and the current
Server Doctor report when one is available. It excludes worlds, settings,
server console output, player lists, add-ons, backups and account data, and
redacts common paths, email addresses, IP addresses, Playit addresses and
secret-like values. The ZIP is never uploaded automatically and should still be
reviewed before sharing.

Manage → Maintenance checks the official catalog for newer server software that still targets the selected server's exact Minecraft version. It can refresh Vanilla, Fabric, Paper and Bedrock server files without silently upgrading the world to another Minecraft release. Every install requires the server to be stopped, creates a complete recovery backup first, verifies published checksums where available and preserves worlds, settings, add-ons and player access files. Older or imported servers can adopt tracked updates after one confirmed reinstall of their current build.

The same Maintenance page can preflight a deliberate move to a newer Minecraft version. Upgrades are forward-only, remain on the same Bedrock Stable or Preview channel and validate the target Java requirement before changing files. Easy Realms checks its managed Fabric mods or Paper plugins against the target version and installs their compatible releases after the server software; unmanaged JARs block the upgrade because their compatibility cannot be proven. A mandatory backup is created first, and any failed software or add-on migration automatically restores the previous server.

Players provides beginner-friendly access management for the selected running server. Java usernames and Bedrock Gamertags are validated before Easy Realms builds fixed allow-list or operator commands, so player text cannot become extra console syntax. Adding a trusted player also enables the edition-appropriate allow-list; removing access revokes operator status first. Operator grants require an explicit warning confirmation. Easy Realms reviews `whitelist.json`, `allowlist.json` and Java `ops.json` read-only, with size and format limits, so the current local access list remains visible while the server is stopped.

Manage → Automation contains optional beginner-friendly protection. Easy Mode detects installed memory and recommends conservative server RAM, view distance and simulation distance values while reserving space for Windows and, when selected, the Minecraft client. Servers can create a retained backup before a manual launch, check the player count and save/stop after a configurable empty period, and restart after an unexpected crash. Crash recovery is capped at three attempts within ten minutes. All automation is off until the user enables and saves it.

The recommended way to let friends join is playit.gg. It gives players a Playit tunnel address instead of your home IP and requires no direct inbound router port. The Share tab detects the separately installed official Playit agent, launches Playit's own one-time browser approval flow, checks its service status and fills in the selected server's loopback tunnel target. For safety, Easy Realms runs only the machine-installed Playit command from Windows Program Files; standalone copies can still be run manually. Playit itself opens the claim page, so Easy Realms never reads, opens or stores claim links, passwords, guest sessions or agent secrets. Separate host and joining instructions explain exactly what to share for Java and Bedrock.

Automatic UPnP port forwarding remains an optional advanced fallback per server. Direct sharing requires verified Minecraft accounts, an enabled player allow-list and explicit approval for the exact server ports once per app session. Easy Realms opens only the selected Minecraft port with a ten-minute lease, renews it every five minutes while the server runs and removes only a mapping that still belongs to Easy Realms. Discovery accepts only explicit local IPv4 gateway ranges, requires the advertised control endpoint to remain on the responding gateway and rejects XML entities, redirects, public destinations and permanent-only routers. Easy Realms does not alter Windows Firewall.

The supplied icon is used for the dashboard and taskbar window. Minecraft Ten is reserved for headings and major launcher-style actions, while Mojangles (Minecraft Seven v2) is used for ordinary interface text, fields, tabs, buttons and console output. The project owner must keep the bundled font notices and confirm redistribution permission for supplied artwork before broad public distribution.

See `RELEASE_NOTES.md`, `PRIVACY.md` and `THIRD_PARTY_NOTICES.txt` for this
release's changes, local-data behaviour and bundled dependency notices.

## Source and rebuilding

The supported Windows ZIP already contains Python, Qt for Python/PySide6 and
Shiboken. The user does not need to install Python, run pip or have administrator
access. `START HERE.cmd` verifies the bundled runtime, interface components,
application modules and required assets before starting the dashboard. If a
file is damaged or missing, it writes the exact failure to `data/logs` and asks
for a fresh extraction instead of opening a broken Python process.

For source development, install Python 3.11+ and run `Start Easy Realms.bat` on
Windows or `python bootstrap.pyw` elsewhere. First launch creates a private
`.venv`, installs every package in `requirements.txt`, upgrades incompatible
versions, verifies the result and only then opens the dashboard. Later launches
reuse that environment and install again only when the requirements are no
longer satisfied.

Java is a server runtime rather than an Easy Realms dependency. Automatic Java
setup remains handled when a Java Edition server is created. Playit is optional
external tunnelling software and is deliberately never installed silently.

The supported public beta is the complete Windows ZIP: `START HERE.cmd` beside
`data/app` and the official bundled `data/runtime`.

Run tests with `python -m unittest -v` from this folder. Full Minecraft server
startup still requires on-device testing. The Python process/UI tests are not a
substitute for that test.

## References

- Python embedded distribution: https://docs.python.org/3.13/using/windows.html#the-embeddable-package
- Runtime packages: https://pypi.org/project/PySide6-Essentials/6.8.3/ and https://pypi.org/project/shiboken6/6.8.3/
- Temurin downloads: https://api.adoptium.net/
- Minecraft EULA: https://www.minecraft.net/eula
- Paper API: https://docs.papermc.io/misc/downloads-service/
- Bedrock Dedicated Server: https://www.minecraft.net/en-us/download/server/bedrock
- Bedrock server setup: https://help.minecraft.net/hc/en-us/articles/49914677714957
- Bedrock server properties: https://learn.microsoft.com/minecraft/creator/documents/bedrockserver/server-properties
- Modrinth API: https://docs.modrinth.com/api/
- Simple Voice Chat with playit: https://playit.gg/support/svc-minecraft/
