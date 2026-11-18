# Easy Realms Public Beta 1.0.2

Release date: 18 November 2026

## Highlights

- Restored square, bevelled Minecraft Launcher-style buttons with distinct
  hover, pressed, focused and disabled states.
- Simplified the Create page by replacing the three boxed setup stages and
  instruction paragraph with a single live compatibility line and a direct
  Import server action.
- Replaced the full-width selected-server banner with a compact title-row
  control that still shows selection and live server state.
- Added first-launch dependency verification. The Windows package verifies its
  bundled Python, PySide6, Shiboken, application modules and required assets;
  source launches create a private environment, automatically install or
  upgrade requirements, and verify them again before opening the dashboard.
- Added the official Minecraft Seven v2/Mojangles font for ordinary interface
  text, fields, tabs, buttons and console output. Minecraft Ten is now reserved
  for headings and major launcher-style actions.
- Kept selected-server and live starting/running information available through
  the compact header control without adding a separate full-width panel.
- Kept concise validation on the configuration page for invalid names, missing
  locations and the remaining Minecraft EULA step.
- Renamed the first creation action to **Continue to setup**, making it clear
  that the next page reviews settings before any files are downloaded.
- Added Ready, Selected and Running badges to My servers, highlights the active
  server, and provides direct Create and Import actions when the library is empty.
- Added clearer navigation tooltips and prevents switching away from a running
  server until it has stopped safely.
- Added a one-click privacy-scrubbed bug report ZIP under About & legal. It
  includes recent Easy Realms diagnostics and basic runtime details while
  excluding worlds, settings, console output, player lists, add-ons, backups
  and account data. Nothing is uploaded automatically.
- Moved the four server-software choices and the Library actions into two compact
  launcher-style dropdown menus with eased opening, hover and click feedback.
- Added a short eased fade and slide when switching between the main tabs.
- Removed Futura from the source and portable package. Minecraft Ten now handles
  headings while Minecraft Seven v2 handles regular interface text.
- Fixed Linux automatic Java setup for the safe internal symbolic links used by
  official Temurin archives. Escaping links and special device files remain
  blocked.
- Added a private, timestamped log for every launch under `data/logs`. It
  records startup failures, unhandled Python and thread errors, Qt errors,
  server-process failures and whether the app shut down cleanly. Logs are never
  uploaded automatically and the oldest files are pruned after 30 launches.
- Added the complete LGPLv3 licence text for the bundled Qt for Python runtime.
- Revalidated the bundled Windows runtime, source parity and clean archive
  contents after the release audit.
- Removed the retired one-file and Microsoft Store packaging experiments, along
  with unused imports and application methods.
- Removed the unreliable native launcher. `START HERE.cmd` is now the single
  entry point, creates the logs folder before checking anything and starts the
  official bundled Python runtime directly.
- Added a first-run Easy Realms End User Agreement. Declining or closing it
  exits the application; acceptance is versioned and stored locally.
- Added a permanent About & legal page and a prominent independent-product
  disclaimer.
- Improved HTTPS request headers and added a secure Linux curl fallback for
  providers that return HTTP 403 to Python's standard network client.
- Added checksum-verified automatic Temurin Java setup for Linux x64 as well as
  Windows x64.
- Added privacy and third-party dependency notices.

## Important testing notes

- This is unsigned public beta software. Windows reputation warnings may still appear.
  Do not disable antivirus protection to run it.
- The Windows portable build must be extracted completely before launching.
- Keep separate backups of important worlds and test upgrades on a copy first.
- The complete ZIP requires a final launch check on a normal Windows 10 or
  Windows 11 x64 computer.

## Known limitations

- Bedrock Dedicated Server creation is Windows-only because Microsoft currently
  supplies the supported Easy Realms Bedrock workflow as a Windows server ZIP.
- Automatic Java setup currently supports x64 Windows and x64 Linux.
- The application itself is not code-signed, so SmartScreen or antivirus
  reputation prompts are still possible.

