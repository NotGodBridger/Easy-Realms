"""Install a verified, private Java runtime on supported desktop systems."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile


def _platform_details():
    machine=platform.machine().lower()
    if machine not in ('x86_64','amd64'):
        raise ValueError('Automatic Java setup currently supports x64 computers. Install the required Java version manually and select its executable.')
    if os.name=='nt':return 'windows','java.exe','zip'
    if sys.platform.startswith('linux'):return 'linux','java','tar.gz'
    raise ValueError('Automatic Java setup currently supports Windows and Linux x64. Install the required Java version manually and select its executable.')


def _request(url):
    return urllib.request.Request(url,headers={
        'User-Agent':'EasyRealms/Public-Beta-1.0.2 (desktop Minecraft server manager)',
        'Accept':'application/json, application/octet-stream;q=0.9, */*;q=0.8',
        'Accept-Encoding':'identity',
    })


def _extract_zip(archive, destination, cancel, cancelled):
    with zipfile.ZipFile(archive) as bundle:
        root=destination.resolve()
        for member in bundle.infolist():
            if cancel.is_set():raise cancelled('Java setup cancelled.')
            target=(destination/member.filename).resolve()
            if not target.is_relative_to(root):raise ValueError('Unsafe path in Java archive.')
            bundle.extract(member,destination)


def _extract_tar(archive, destination, cancel, cancelled):
    with tarfile.open(archive,'r:gz') as bundle:
        root=destination.resolve();members=bundle.getmembers()
        for member in members:
            if cancel.is_set():raise cancelled('Java setup cancelled.')
            target=(destination/member.name).resolve()
            if not target.is_relative_to(root):raise ValueError('Unsafe path in Java archive.')
            if member.issym():
                link_target=(target.parent/member.linkname).resolve()
                if not link_target.is_relative_to(root):raise ValueError('Unsafe symbolic link in Java archive.')
            elif member.islnk():
                link_target=(destination/member.linkname).resolve()
                if not link_target.is_relative_to(root):raise ValueError('Unsafe hard link in Java archive.')
            elif not (member.isdir() or member.isfile()):
                raise ValueError('Unsupported special file in Java archive.')
        try:
            bundle.extractall(destination,members=members,filter='data')
        except TypeError:
            # Python 3.11 releases before the tar filter backport still use our
            # complete path/link/type validation above.
            bundle.extractall(destination,members=members)


def ensure_java(required, chosen, progress, cancel, detect):
    automatic=chosen.strip().lower() in ('automatic','auto','java','')
    try:
        if detect('java' if automatic else chosen)==required:return 'java' if automatic else chosen
    except ValueError:
        if not automatic:raise
    if not automatic:raise ValueError(f'Select Java {required}, or enter Automatic to download it.')

    operating_system,binary_name,archive_type=_platform_details()
    data=Path(os.environ.get('EASY_REALMS_DATA',Path(__file__).resolve().parent/'data'))
    home=data/'java';target=home/str(required)
    found=list(target.glob(f'*/bin/{binary_name}')) if target.exists() else []
    if found and detect(str(found[0]))==required:return str(found[0])

    from backend import Cancelled
    home.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix=f'.java-{required}-',dir=home))
    try:
        progress(0,f'Finding Java {required} for {operating_system.title()}…')
        metadata_url=(f'https://api.adoptium.net/v3/assets/latest/{required}/hotspot?'
                      f'architecture=x64&image_type=jre&os={operating_system}&vendor=eclipse')
        with urllib.request.urlopen(_request(metadata_url),timeout=30) as response:items=json.load(response)
        if not items:raise ValueError(f'No automatic Java {required} download is available. Install it manually and select the java executable.')
        package=items[0]['binary']['package'];digest=hashlib.sha256();archive=stage/f'java.{archive_type}'
        with urllib.request.urlopen(_request(package['link']),timeout=60) as response,archive.open('wb') as output:
            total=int(response.headers.get('Content-Length',0));received=0
            while True:
                if cancel.is_set():raise Cancelled('Java setup cancelled.')
                chunk=response.read(256*1024)
                if not chunk:break
                output.write(chunk);digest.update(chunk);received+=len(chunk)
                progress(min(90,int(received*90/total)) if total else 0,f'Downloading Java {required}: {received/1048576:.1f} MB')
            if total and received!=total:raise ValueError('Incomplete Java download. Please retry.')
        if digest.hexdigest().lower()!=str(package['checksum']).lower():raise ValueError('Java download checksum failed. Please retry.')

        progress(95,'Installing Java into data/java…')
        unpack=stage/'unpacked';unpack.mkdir()
        if archive_type=='zip':_extract_zip(archive,unpack,cancel,Cancelled)
        else:_extract_tar(archive,unpack,cancel,Cancelled)
        found=list(unpack.glob(f'*/bin/{binary_name}'))
        if not found:raise ValueError('Downloaded Java runtime did not contain the expected executable.')
        if operating_system=='linux':found[0].chmod(found[0].stat().st_mode|0o111)
        if detect(str(found[0]))!=required:raise ValueError('Downloaded Java runtime failed validation.')
        relative=found[0].relative_to(unpack)
        if target.exists():shutil.rmtree(target)
        unpack.rename(target)
        return str(target/relative)
    finally:
        shutil.rmtree(stage,ignore_errors=True)
