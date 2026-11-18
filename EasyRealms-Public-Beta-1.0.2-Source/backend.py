"""Official server catalogs and transactional server creation. No GUI dependency."""
from __future__ import annotations
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import sys
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit
import zipfile

from legal import APP_VERSION

USER_AGENT_VERSION = APP_VERSION.replace(' ', '-')

MOJANG = 'https://piston-meta.mojang.com/mc/game/version_manifest_v2.json'
FABRIC = 'https://meta.fabricmc.net/v2/versions'
PAPER = 'https://fill.papermc.io/v3/projects/paper'
BEDROCK = 'https://www.minecraft.net/en-us/download/server/bedrock'
BEDROCK_LINKS = 'https://net-secondary.web.minecraft-services.net/api/v1.0/download/links'

class Cancelled(Exception):
    pass


class _TemporaryResponse:
    """Small response adapter for curl's verified temporary-file fallback."""
    def __init__(self, stream):
        self.stream=stream;self.headers={}
    def read(self, size=-1):return self.stream.read(size)
    def close(self):self.stream.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()

class Catalog:
    def __init__(self, contact=''):
        self.contact = contact.strip()
        self.cache = {}

    @staticmethod
    def valid_contact(contact):
        return bool(re.match(r'^(https://\S+|[^\s@]+@[^\s@]+\.[^\s@]+)$',contact))

    @staticmethod
    def is_paper_url(url):
        return (urlsplit(url).hostname or '').lower()=='fill.papermc.io'

    def user_agent(self, url):
        if self.is_paper_url(url):
            if not self.valid_contact(self.contact):
                raise ValueError('Paper requires a public contact URL or email in its download requests. Enter yours below, then refresh.')
            return f'EasyRealms/{USER_AGENT_VERSION} ({self.contact})'
        return f'EasyRealms/{USER_AGENT_VERSION} (desktop Minecraft server manager)'

    def request(self, url):
        if not url.startswith('https://'):
            raise ValueError('Only HTTPS downloads are supported.')
        return urllib.request.Request(url, headers={
            'User-Agent':self.user_agent(url),
            'Accept':'application/json, application/octet-stream;q=0.9, */*;q=0.8',
            'Accept-Encoding':'identity',
            'Cache-Control':'no-cache',
        })

    def open(self, url, timeout=30):
        request=self.request(url)
        try:return urllib.request.urlopen(request,timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code!=403:raise
            # Some Linux distributions/proxies reject urllib's TLS fingerprint
            # even when the provider accepts the same explicit headers. Use the
            # installed curl client without a shell and keep HTTPS-only redirects.
            curl=shutil.which('curl') if sys.platform.startswith('linux') else None
            if curl:
                output=tempfile.TemporaryFile()
                try:
                    result=subprocess.run([
                        curl,'--fail','--silent','--show-error','--location',
                        '--proto','=https','--proto-redir','=https',
                        '--connect-timeout',str(min(timeout,30)),'--max-time',str(timeout),
                        '--user-agent',self.user_agent(url),
                        '--header','Accept: application/json, application/octet-stream;q=0.9, */*;q=0.8',
                        '--header','Accept-Encoding: identity','--header','Cache-Control: no-cache',url,
                    ],stdout=output,stderr=subprocess.PIPE,timeout=timeout+5)
                except (OSError,subprocess.TimeoutExpired):
                    result=None
                if result is not None and result.returncode==0:
                    output.seek(0);return _TemporaryResponse(output)
                output.close()
            provider='PaperMC' if self.is_paper_url(url) else (urlsplit(url).hostname or 'The download provider')
            raise ValueError(f'{provider} refused the download (HTTP 403). Check the Paper contact field if shown, your system clock, proxy or VPN, then try Refresh.') from exc

    def get(self, url):
        if url not in self.cache:
            with self.open(url,timeout=30) as response:
                self.cache[url] = json.load(response)
        return self.cache[url]

    def get_text(self, url):
        key = 'text:' + url
        if key not in self.cache:
            with self.open(url,timeout=30) as response:
                self.cache[key] = response.read().decode('utf-8', errors='replace')
        return self.cache[key]

    @staticmethod
    def parse_bedrock_downloads(page):
        page = html.unescape(page).replace('\\/', '/').replace('\\u002F', '/').replace('\\u002f', '/')
        pattern = re.compile(r'(?P<url>(?:https://www\.minecraft\.net)?/bedrockdedicatedserver/(?P<channel>bin-win[^/"\'<>\s]*)/bedrock-server-(?P<version>[0-9][0-9A-Za-z._+-]*)\.zip)', re.I)
        result = {}
        for match in pattern.finditer(page):
            url = match.group('url')
            if url.startswith('/'): url = 'https://www.minecraft.net' + url
            preview = 'preview' in match.group('channel').lower()
            label = ('Preview ' if preview else '') + match.group('version')
            result.setdefault(label, url)
        stable = [(label, url) for label, url in result.items() if not label.startswith('Preview ')]
        preview = [(label, url) for label, url in result.items() if label.startswith('Preview ')]
        return dict(stable + preview)

    @staticmethod
    def parse_bedrock_api(payload):
        expected={'serverBedrockWindows':False,'serverBedrockPreviewWindows':True}
        links=payload.get('result',{}).get('links',[]) if isinstance(payload,dict) else []
        result={}
        pattern=re.compile(r'^https://www\.minecraft\.net/bedrockdedicatedserver/(?P<channel>bin-win(?:-preview)?)/bedrock-server-(?P<version>[0-9][0-9A-Za-z._+-]*)\.zip$',re.I)
        for item in links:
            if not isinstance(item,dict) or item.get('downloadType') not in expected:continue
            match=pattern.fullmatch(str(item.get('downloadUrl','')))
            if not match:continue
            preview=expected[item['downloadType']]
            if ('preview' in match.group('channel').lower())!=preview:continue
            label=('Preview ' if preview else '')+match.group('version')
            result.setdefault(label,match.group(0))
        return result

    def bedrock_downloads(self):
        try:downloads=self.parse_bedrock_api(self.get(BEDROCK_LINKS))
        except Exception:downloads={}
        if not downloads:
            downloads = self.parse_bedrock_downloads(self.get_text(BEDROCK))
        if not downloads:
            raise ValueError('Minecraft did not publish a usable Bedrock Windows download. Refresh later or import a server downloaded from minecraft.net.')
        return downloads

    def versions(self, kind):
        if kind == 'Bedrock':
            return list(self.bedrock_downloads())
        releases = [v['id'] for v in self.get(MOJANG)['versions'] if v['type'] == 'release']
        if kind == 'Vanilla':
            return releases
        if kind == 'Fabric':
            supported = {v['version'] for v in self.get(FABRIC + '/game') if v.get('stable')}
        else:
            if not self.valid_contact(self.contact):
                raise ValueError('Paper requires a contact URL or email in its download requests. Enter yours below, then refresh.')
            groups = self.get(PAPER)['versions']
            supported = {v for group in groups.values() for v in group} if isinstance(groups, dict) else set(groups)
        return [v for v in releases if v in supported]

    def resolve(self, kind, version):
        if kind == 'Bedrock':
            url = self.bedrock_downloads().get(version)
            if not url:
                raise ValueError('That Bedrock build is no longer offered by Minecraft. Refresh the list.')
            return dict(kind=kind, version=version, java=None, detail='Official Windows server • No Java required', url=url, checksum=None, algorithm='sha256')
        entry = next((v for v in self.get(MOJANG)['versions'] if v['id'] == version), None)
        if entry is None:
            raise ValueError('Minecraft version is no longer in the official catalog. Refresh the list.')
        meta = self.get(entry['url'])
        java = meta.get('javaVersion', {}).get('majorVersion', 8)
        vanilla = meta.get('downloads', {}).get('server')
        if not vanilla:
            raise ValueError('Mojang does not publish a server download for this version. Choose another version.')
        result = dict(kind=kind, version=version, java=java, detail=version)
        if kind == 'Vanilla':
            return dict(result, url=vanilla['url'], checksum=vanilla['sha1'], algorithm='sha1')
        if kind == 'Fabric':
            loaders = self.get(FABRIC + '/loader/' + quote(version, safe=''))
            loader = next((x['loader']['version'] for x in loaders if x['loader'].get('stable')), None)
            installers = self.get(FABRIC + '/installer')
            installer = next((x['version'] for x in installers if x.get('stable')), None)
            if not loader or not installer:
                raise ValueError('No stable Fabric loader/installer is available for this Minecraft version.')
            return dict(result, url=f'{FABRIC}/loader/{quote(version)}/{quote(loader)}/{quote(installer)}/server/jar',
                        checksum=None, algorithm='sha256', detail=f'Loader {loader} • Installer {installer}')
        builds = self.get(PAPER + '/versions/' + quote(version, safe='') + '/builds')
        stable = [b for b in builds if b.get('channel') in ('STABLE', 'RECOMMENDED') and 'server:default' in b.get('downloads', {})]
        if not stable:
            raise ValueError('Paper has no stable server build for this version. Choose another version.')
        build = max(stable, key=lambda b: int(b['id']))
        download = build['downloads']['server:default']
        # Paper can require a newer Java runtime than vanilla.
        parts = tuple(int(x) for x in version.split('.'))
        paper_java = 25 if parts >= (26, 1) else 21 if parts >= (1, 20) else 17 if parts >= (1, 17) else 16 if parts >= (1, 16, 5) else 11 if parts >= (1, 12) else 8
        return dict(result, java=max(java, paper_java), url=download['url'], checksum=download['checksums']['sha256'],
                    algorithm='sha256', detail=f"Stable build {build['id']}")


def java_major(executable):
    try:
        process = subprocess.run([executable, '-version'], capture_output=True, text=True, timeout=15,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Java could not be started. Install the required Java version, or select its java executable.') from exc
    match = re.search(r'version\s+"(?:1\.)?(\d+)', process.stderr + process.stdout)
    if process.returncode or not match:
        raise ValueError('Could not determine this Java runtime version.')
    return int(match.group(1))


def validate_name(name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _-]{0,59}', name) or name.endswith(' '):
        raise ValueError('Use 1–60 letters, numbers, spaces, hyphens or underscores; start with a letter or number.')
    if name.upper() in {'CON','PRN','AUX','NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))}:
        raise ValueError('That name is reserved by Windows.')


def create_server(catalog, spec, parent, name, ram, java, accepted, progress, cancel):
    validate_name(name)
    if not accepted:
        raise ValueError('You must accept the Minecraft EULA before creating a server.')
    if not 1 <= ram <= 128:
        raise ValueError('RAM must be between 1 and 128 GB.')
    if spec['kind'] == 'Bedrock':
        return create_bedrock_server(catalog, spec, parent, name, accepted, progress, cancel)
    from java_runtime import ensure_java
    java = ensure_java(spec['java'], java, progress, cancel, java_major)
    actual = java_major(java)
    if actual != spec['java']:
        raise ValueError(f"This setup targets Java {spec['java']}; selected Java is {actual}. Select the matching runtime for compatibility.")
    parent = Path(parent).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / name
    if target.exists():
        raise ValueError('A folder with that name already exists. Choose a new name; existing worlds are never overwritten.')
    temp = Path(tempfile.mkdtemp(prefix='.easyservers-', dir=parent))
    try:
        progress(0, 'Downloading server…')
        digest = hashlib.new(spec['algorithm'])
        with catalog.open(spec['url'],timeout=45) as response, (temp/'server.jar').open('wb') as output:
            total = int(response.headers.get('Content-Length', 0))
            received = 0
            while True:
                if cancel.is_set():
                    raise Cancelled('Creation cancelled. Temporary files removed.')
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                progress(min(95, int(received * 95 / total)) if total else 0, f'Downloaded {received / 1048576:.1f} MB')
            if total and received != total:
                raise ValueError('Incomplete download. Please retry.')
        if spec['checksum'] and digest.hexdigest().lower() != spec['checksum'].lower():
            raise ValueError('Download checksum mismatch. Please retry.')
        if not zipfile.is_zipfile(temp/'server.jar'):
            raise ValueError('The download is not a valid server JAR.')
        if cancel.is_set():
            raise Cancelled('Creation cancelled. Temporary files removed.')
        (temp/'eula.txt').write_text('eula=true\n', encoding='utf-8')
        (temp/'server.properties').write_text('online-mode=true\nserver-port=25565\nmotd=An Easy Realms Minecraft server\nview-distance=8\n', encoding='utf-8')
        installed_build={key:spec.get(key) for key in ('kind','version','detail','url','checksum','algorithm')}
        config = dict(spec, name=name, ram=ram, java=java, installed_build=installed_build)
        (temp/'easyservers.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
        # Launch through Python to avoid embedding user paths into shell commands.
        (temp/'launch.py').write_text('import json, subprocess\nfrom pathlib import Path\np=Path(__file__).resolve().parent\nc=json.loads((p/"easyservers.json").read_text())\nraise SystemExit(subprocess.call([c["java"], "-Xms1G", "-Xmx"+str(c["ram"])+"G", "-jar", "server.jar", "nogui"], cwd=p))\n', encoding='utf-8')
        (temp/'Start Server.bat').write_text('@echo off\ncd /d "%~dp0"\n"'+__import__('sys').executable.replace('"','')+'" launch.py\npause\n', encoding='utf-8')
        (temp/'start-server.sh').write_text('#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\nexec python3 launch.py\n', encoding='utf-8')
        (temp/'start-server.sh').chmod(0o755)
        if spec['kind'] == 'Fabric': (temp/'mods').mkdir()
        if spec['kind'] == 'Paper': (temp/'plugins').mkdir()
        if target.exists():
            raise ValueError('Destination appeared during download. Choose another name.')
        temp.rename(target)
        progress(100, 'Server created. Ready to launch.')
        return str(target)
    finally:
        if temp.exists(): shutil.rmtree(temp)


def create_bedrock_server(catalog, spec, parent, name, accepted, progress, cancel):
    """Download and transactionally install the official Windows BDS ZIP."""
    validate_name(name)
    if not accepted:
        raise ValueError('You must accept the Minecraft EULA before creating a server.')
    parent = Path(parent).expanduser().resolve()
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / name
    if target.exists():
        raise ValueError('A folder with that name already exists. Choose a new name; existing worlds are never overwritten.')
    temp = Path(tempfile.mkdtemp(prefix='.easyrealms-bedrock-', dir=parent))
    archive_path = temp / 'bedrock-server.zip'
    try:
        progress(0, 'Downloading the official Bedrock server…')
        with catalog.open(spec['url'],timeout=60) as response, archive_path.open('wb') as output:
            total = int(response.headers.get('Content-Length', 0));received = 0
            while True:
                if cancel.is_set():raise Cancelled('Creation cancelled. Temporary files removed.')
                chunk = response.read(256 * 1024)
                if not chunk:break
                output.write(chunk);received += len(chunk)
                progress(min(80, int(received * 80 / total)) if total else 0, f'Downloaded {received / 1048576:.1f} MB')
            if total and received != total:raise ValueError('Incomplete download. Please retry.')
        if not zipfile.is_zipfile(archive_path):raise ValueError('Minecraft returned an invalid Bedrock server ZIP.')
        progress(84, 'Checking and extracting Bedrock server files…')
        with zipfile.ZipFile(archive_path) as archive:
            root = temp.resolve()
            for member in archive.infolist():
                destination = (temp / member.filename).resolve()
                if root not in destination.parents and destination != root:
                    raise ValueError('The Bedrock download contains an unsafe file path.')
            archive.extractall(temp)
        archive_path.unlink()
        executable = temp / 'bedrock_server.exe'
        if not executable.is_file():raise ValueError('The Bedrock download did not contain bedrock_server.exe.')
        from server_manager import update_properties
        update_properties(temp, {'server-name':name, 'transport':'nethernet'})
        installed_build={key:spec.get(key) for key in ('kind','version','detail','url','checksum','algorithm')}
        config = dict(spec, name=name, ram=0, executable='bedrock_server.exe', platform='windows', installed_build=installed_build)
        (temp/'easyservers.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
        (temp/'Start Server.bat').write_text('@echo off\ncd /d "%~dp0"\nbedrock_server.exe\npause\n', encoding='utf-8')
        if target.exists():raise ValueError('Destination appeared during download. Choose another name.')
        temp.rename(target);progress(100, 'Bedrock server created. Ready to launch.');return str(target)
    finally:
        if temp.exists():shutil.rmtree(temp)
