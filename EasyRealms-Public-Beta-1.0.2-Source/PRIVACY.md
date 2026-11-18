# Easy Realms privacy summary

Easy Realms is designed as a local-first desktop application. It does not
include analytics, advertising, account tracking or automatic diagnostic
uploads.

## Data stored locally

Easy Realms may store server locations and settings, Java runtimes, backups,
managed add-on records, acceptance of the current Easy Realms agreement and
diagnostic logs inside its `data` folder. Minecraft worlds remain in the server
folders selected by the user. Removing a server from the app does not delete its
world.

Diagnostic logs can contain local file paths, server names and technical error
messages. Review a log before sharing it publicly. Easy Realms never uploads
these logs automatically. A separate timestamped log is created for each launch
inside `data/logs`, and Easy Realms keeps at most the 30 newest launch logs.

The optional **Export bug report** action creates a ZIP on the user's computer.
It includes basic runtime details, up to five recent Easy Realms logs and an
optional Server Doctor report. Easy Realms excludes worlds, settings, server
console output, player lists, add-ons, backups, Java runtimes and Playit account
data. It also replaces common home paths, email addresses, IP addresses, Playit
addresses and secret-like values. The ZIP is not uploaded automatically. Users
should still review its text files before sharing them.

## Network connections

When requested by the user, Easy Realms connects directly to the relevant
provider to obtain catalogs or downloads. Providers may include Mojang or
Microsoft, Fabric, PaperMC, Modrinth, Eclipse Adoptium and Playit. Those
providers receive normal connection information such as the user's IP address
and user-agent string and apply their own privacy policies.

PaperMC requires a public project URL or contact email in its download
user-agent. Easy Realms sends that value only to PaperMC download endpoints.
Easy Realms does not operate a central account service and does not receive the
value.

Playit account approval and tunnel management occur through Playit's official
agent and website. Easy Realms does not request or store Playit passwords,
claim links or agent secrets.

## User control

Deleting the Easy Realms `data` folder removes the app's local settings,
downloaded runtimes and records, but may also remove default-location servers
and backups stored beneath that folder. Back up worlds before deleting data.

