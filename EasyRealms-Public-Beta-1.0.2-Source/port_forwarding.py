"""Small, dependency-free UPnP IGD client for temporary Minecraft mappings.

Easy Realms deliberately limits this module to private-network devices and the
exact ports requested by a server.  It never changes Windows Firewall rules.
"""
from __future__ import annotations

from dataclasses import dataclass
import html
import ipaddress
import socket
import time
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET


SSDP_ADDRESS = ("239.255.255.250", 1900)
MAX_RESPONSE = 1024 * 1024
LEASE_SECONDS = 10 * 60
LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "100.64.0.0/10")
)
ALLOWED_SERVICES = {
    f"urn:schemas-upnp-org:service:{name}:{version}"
    for name in ("WANIPConnection", "WANPPPConnection")
    for version in ("1", "2")
}


class PortForwardingError(RuntimeError):
    pass


@dataclass(frozen=True)
class GatewayService:
    service_type: str
    control_url: str
    gateway_ip: str


@dataclass(frozen=True)
class MappingRequest:
    protocol: str
    port: int


@dataclass(frozen=True)
class ActiveMapping:
    service: GatewayService
    protocol: str
    port: int
    internal_ip: str
    external_ip: str = ""
    description: str = "Easy Realms"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PortForwardingError("The router redirected its UPnP request, so Easy Realms stopped for safety.")


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def _local_network_address(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise PortForwardingError("The router advertised a non-local UPnP host.") from exc
    if not isinstance(address, ipaddress.IPv4Address) or not any(address in network for network in LOCAL_NETWORKS):
        raise PortForwardingError("The router advertised a UPnP address outside the local private network.")
    return address


def _private_url(url, *, expected_host=None):
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise PortForwardingError("The router advertised an unsafe UPnP address.")
    address = _local_network_address(parsed.hostname)
    if expected_host is not None and address != _local_network_address(expected_host):
        raise PortForwardingError("The router tried to move its UPnP control request to another device, so Easy Realms stopped.")
    return parsed


def _safe_xml(payload, label="UPnP response"):
    lowered = payload.lower()
    doctype = b"<!doctype" if isinstance(lowered, bytes) else "<!doctype"
    entity = b"<!entity" if isinstance(lowered, bytes) else "<!entity"
    if doctype in lowered or entity in lowered:
        raise PortForwardingError(f"The router returned an unsafe {label}.")
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise PortForwardingError(f"The router returned invalid {label}.") from exc


def _read_local(url, *, data=None, headers=None, timeout=4):
    _private_url(url)
    request = Request(url, data=data, headers=headers or {})
    opener = build_opener(_NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        payload = response.read(MAX_RESPONSE + 1)
    if len(payload) > MAX_RESPONSE:
        raise PortForwardingError("The router returned an unexpectedly large UPnP response.")
    return payload


def parse_gateway_service(description, location):
    """Return the preferred WAN IP/PPP connection service from device XML."""
    parsed = _private_url(location)
    root = _safe_xml(description, "UPnP device information")
    services = []
    for service in (item for item in root.iter() if _local_name(item.tag) == "service"):
        fields = {_local_name(child.tag): (child.text or "").strip() for child in service}
        service_type = fields.get("serviceType", "")
        control = fields.get("controlURL", "")
        if control and service_type in ALLOWED_SERVICES:
            control_url = urljoin(location, control)
            _private_url(control_url, expected_host=parsed.hostname)
            priority = (0 if "WANIPConnection" in service_type else 1,
                        0 if service_type.endswith(":2") else 1)
            services.append((priority, GatewayService(service_type, control_url, parsed.hostname)))
    if not services:
        raise PortForwardingError("This router did not advertise a UPnP internet gateway service.")
    return min(services, key=lambda item: item[0])[1]


def mapping_requests(kind, properties):
    """Select only the public mappings required by this server configuration."""
    default_port = 19132 if kind == "Bedrock" else 25565
    try:
        port = int(properties.get("server-port", default_port))
    except (TypeError, ValueError) as exc:
        raise PortForwardingError("The server port in server.properties is not a number.") from exc
    if not 1 <= port <= 65535:
        raise PortForwardingError("The server port must be between 1 and 65535.")
    if kind == "Bedrock":
        # Minecraft's current NetherNet guidance requires the signalling port
        # on both protocols. RakNet-only servers use UDP.
        transport = str(properties.get("transport", "nethernet")).strip().lower()
        protocols = ("UDP",) if transport == "raknet" else ("TCP", "UDP")
    else:
        protocols = ("TCP",)
    return [MappingRequest(protocol, port) for protocol in protocols]


class PortForwarder:
    def __init__(self, discovery_timeout=2.5):
        self.discovery_timeout = discovery_timeout

    def discover(self):
        locations = []
        searches = (
            "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
            "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
        )
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.settimeout(0.25)
            for search in searches:
                message = ("M-SEARCH * HTTP/1.1\r\n"
                           "HOST: 239.255.255.250:1900\r\n"
                           'MAN: "ssdp:discover"\r\n'
                           "MX: 2\r\n"
                           f"ST: {search}\r\n\r\n")
                sock.sendto(message.encode("ascii"), SSDP_ADDRESS)
            deadline = time.monotonic() + self.discovery_timeout
            while time.monotonic() < deadline:
                try:
                    packet, sender = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                headers = {}
                for line in packet.decode("iso-8859-1", errors="replace").split("\r\n")[1:]:
                    if ":" in line:
                        key, value = line.split(":", 1)
                        headers[key.strip().lower()] = value.strip()
                location = headers.get("location")
                if location and location not in locations:
                    try:
                        parsed = _private_url(location)
                        if _local_network_address(sender[0]) != _local_network_address(parsed.hostname):
                            continue
                    except PortForwardingError:
                        continue
                    locations.append(location)
        finally:
            sock.close()
        errors = []
        for location in locations:
            try:
                return parse_gateway_service(_read_local(location), location)
            except (OSError, HTTPError, PortForwardingError) as exc:
                errors.append(str(exc))
        if errors:
            raise PortForwardingError(errors[-1])
        raise PortForwardingError("No UPnP router was found. UPnP may be disabled, unsupported, or blocked on this network.")

    @staticmethod
    def internal_ip(service):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((service.gateway_ip, 9))
            address = sock.getsockname()[0]
        finally:
            sock.close()
        _local_network_address(address)
        return address

    @staticmethod
    def _soap(service, action, arguments):
        fields = "".join(f"<{key}>{html.escape(str(value))}</{key}>" for key, value in arguments.items())
        body = (f'<?xml version="1.0"?>'
                f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
                f'<s:Body><u:{action} xmlns:u="{service.service_type}">{fields}</u:{action}></s:Body></s:Envelope>').encode("utf-8")
        headers = {"Content-Type": 'text/xml; charset="utf-8"',
                   "SOAPACTION": f'"{service.service_type}#{action}"'}
        try:
            return _read_local(service.control_url, data=body, headers=headers)
        except HTTPError as exc:
            payload = exc.read(MAX_RESPONSE).decode("utf-8", errors="replace")
            try:
                root = _safe_xml(payload)
                detail = next((node.text for node in root.iter() if _local_name(node.tag) == "errorDescription" and node.text), None)
                code = next((node.text for node in root.iter() if _local_name(node.tag) == "errorCode" and node.text), None)
            except PortForwardingError:
                detail = code = None
            message = detail or (f"UPnP error {code}" if code else f"router error {exc.code}")
            if code == "718":
                message = "that port is already forwarded by this router"
            raise PortForwardingError(f"The router could not {action}: {message}.") from exc
        except OSError as exc:
            raise PortForwardingError("The router stopped responding while Easy Realms changed the port mapping.") from exc

    def open(self, requests, description):
        service = self.discover()
        internal_ip = self.internal_ip(service)
        external_ip = ""
        try:
            response = self._soap(service, "GetExternalIPAddress", {})
            root = _safe_xml(response)
            external_ip = next((node.text.strip() for node in root.iter()
                                if _local_name(node.tag) == "NewExternalIPAddress" and node.text), "")
            if external_ip:
                ipaddress.ip_address(external_ip)
        except (PortForwardingError, ValueError):
            external_ip = ""
        active = []
        safe_description = "".join(ch for ch in description if ch.isalnum() or ch in " ._-")[:48] or "Easy Realms"
        try:
            for request in requests:
                arguments = self._mapping_arguments(request.protocol, request.port, internal_ip, safe_description)
                try:
                    self._soap(service, "AddPortMapping", arguments)
                except PortForwardingError as exc:
                    if "OnlyPermanentLeasesSupported" in str(exc) or "725" in str(exc):
                        raise PortForwardingError(
                            "This router accepts only permanent UPnP rules. Easy Realms refused to create one; use Playit instead."
                        ) from exc
                    raise
                active.append(ActiveMapping(service, request.protocol, request.port, internal_ip, external_ip, safe_description))
        except Exception:
            try:
                self.close(active, verify=False)
            except PortForwardingError:
                pass
            raise
        return active

    @staticmethod
    def _mapping_arguments(protocol, port, internal_ip, description):
        protocol = str(protocol).upper()
        if protocol not in {"TCP", "UDP"}:
            raise PortForwardingError("Easy Realms refused an invalid port-mapping protocol.")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise PortForwardingError("Easy Realms refused an invalid port-mapping number.")
        _local_network_address(internal_ip)
        return {
            "NewRemoteHost": "",
            "NewExternalPort": port,
            "NewProtocol": protocol,
            "NewInternalPort": port,
            "NewInternalClient": internal_ip,
            "NewEnabled": 1,
            "NewPortMappingDescription": description,
            "NewLeaseDuration": LEASE_SECONDS,
        }

    def _specific_mapping(self, mapping):
        """Return the router's current owner fields, or None if expired."""

        try:
            response = self._soap(mapping.service, "GetSpecificPortMappingEntry", {
                "NewRemoteHost": "",
                "NewExternalPort": mapping.port,
                "NewProtocol": mapping.protocol,
            })
        except PortForwardingError as exc:
            if "714" in str(exc) or "NoSuchEntryInArray" in str(exc):
                return None
            raise
        root = _safe_xml(response)
        return {
            _local_name(node.tag): (node.text or "").strip()
            for node in root.iter()
            if _local_name(node.tag) in {"NewInternalPort", "NewInternalClient", "NewPortMappingDescription"}
        }

    @staticmethod
    def _owns_mapping(mapping, fields):
        if fields is None:
            return False
        return (
            fields.get("NewInternalPort") == str(mapping.port)
            and fields.get("NewInternalClient") == mapping.internal_ip
            and fields.get("NewPortMappingDescription") == mapping.description
        )

    def renew(self, mappings, description="Easy Realms"):
        """Renew only mappings already opened by this Easy Realms session."""
        safe_description = "".join(ch for ch in description if ch.isalnum() or ch in " ._-")[:48] or "Easy Realms"
        for mapping in mappings:
            current = self._specific_mapping(mapping)
            if current is not None and not self._owns_mapping(mapping, current):
                raise PortForwardingError(
                    f"The router's {mapping.protocol} {mapping.port} rule no longer belongs to Easy Realms, so it was not renewed."
                )
            arguments = self._mapping_arguments(
                mapping.protocol,
                mapping.port,
                mapping.internal_ip,
                safe_description,
            )
            try:
                self._soap(mapping.service, "AddPortMapping", arguments)
            except PortForwardingError as exc:
                if "OnlyPermanentLeasesSupported" in str(exc) or "725" in str(exc):
                    raise PortForwardingError(
                        "The router would renew this port only as a permanent rule, so Easy Realms stopped renewing it."
                    ) from exc
                raise
        return list(mappings)

    def close(self, mappings, *, verify=True):
        errors = []
        for mapping in reversed(list(mappings)):
            try:
                if verify:
                    current = self._specific_mapping(mapping)
                    if current is None:
                        continue
                    if not self._owns_mapping(mapping, current):
                        raise PortForwardingError(
                            f"The router's {mapping.protocol} {mapping.port} rule no longer belongs to Easy Realms, so it was left untouched."
                        )
                self._soap(mapping.service, "DeletePortMapping", {
                    "NewRemoteHost": "", "NewExternalPort": mapping.port,
                    "NewProtocol": mapping.protocol,
                })
            except PortForwardingError as exc:
                errors.append(str(exc))
        if errors:
            raise PortForwardingError(errors[-1])

