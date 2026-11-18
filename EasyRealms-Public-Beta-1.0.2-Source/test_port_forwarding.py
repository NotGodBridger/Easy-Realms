import unittest
from unittest.mock import patch

from port_forwarding import (ActiveMapping, GatewayService, MappingRequest,
    PortForwarder, PortForwardingError, mapping_requests, parse_gateway_service)


DEVICE = b'''<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0"><device><serviceList>
<service><serviceType>urn:schemas-upnp-org:service:WANPPPConnection:1</serviceType><controlURL>/ppp</controlURL></service>
<service><serviceType>urn:schemas-upnp-org:service:WANIPConnection:2</serviceType><controlURL>/upnp/control/WANIPConn2</controlURL></service>
</serviceList></device></root>'''


class PortForwardingTests(unittest.TestCase):
    def test_selects_java_custom_tcp_port(self):
        self.assertEqual(mapping_requests("Paper", {"server-port": "25570"}), [MappingRequest("TCP", 25570)])

    def test_selects_bedrock_nethernet_tcp_and_udp(self):
        self.assertEqual(mapping_requests("Bedrock", {"server-port": "19132", "transport": "nethernet"}),
                         [MappingRequest("TCP", 19132), MappingRequest("UDP", 19132)])

    def test_selects_bedrock_raknet_udp(self):
        self.assertEqual(mapping_requests("Bedrock", {"transport": "raknet"}), [MappingRequest("UDP", 19132)])

    def test_rejects_invalid_port(self):
        with self.assertRaises(PortForwardingError):
            mapping_requests("Vanilla", {"server-port": "70000"})

    def test_prefers_wan_ip_v2_and_resolves_control_url(self):
        service = parse_gateway_service(DEVICE, "http://192.168.1.1:5000/root.xml")
        self.assertEqual(service.service_type, "urn:schemas-upnp-org:service:WANIPConnection:2")
        self.assertEqual(service.control_url, "http://192.168.1.1:5000/upnp/control/WANIPConn2")

    def test_rejects_public_router_description(self):
        with self.assertRaises(PortForwardingError):
            parse_gateway_service(DEVICE, "http://8.8.8.8/root.xml")

    def test_rejects_loopback_router_description(self):
        with self.assertRaises(PortForwardingError):
            parse_gateway_service(DEVICE, "http://127.0.0.1/root.xml")

    def test_rejects_control_url_on_another_private_device(self):
        moved = DEVICE.replace(b"/upnp/control/WANIPConn2", b"http://192.168.1.22/control")
        with self.assertRaisesRegex(PortForwardingError, "another device"):
            parse_gateway_service(moved, "http://192.168.1.1/root.xml")

    def test_rejects_xml_entities(self):
        unsafe = b'<!DOCTYPE root [<!ENTITY x "test">]><root>&x;</root>'
        with self.assertRaisesRegex(PortForwardingError, "unsafe"):
            parse_gateway_service(unsafe, "http://192.168.1.1/root.xml")

    def test_rolls_back_if_second_mapping_fails(self):
        forwarder = PortForwarder()
        service = GatewayService("urn:schemas-upnp-org:service:WANIPConnection:1", "http://192.168.1.1/control", "192.168.1.1")
        calls = []
        def soap(_, action, args):
            if action == "GetExternalIPAddress":
                return b'<Envelope><NewExternalIPAddress>203.0.113.5</NewExternalIPAddress></Envelope>'
            calls.append((action, args["NewProtocol"]))
            if action == "AddPortMapping" and args["NewProtocol"] == "UDP":
                raise PortForwardingError("failed")
        with patch.object(forwarder, "discover", return_value=service), patch.object(forwarder, "internal_ip", return_value="192.168.1.50"), patch.object(forwarder, "_soap", side_effect=soap):
            with self.assertRaises(PortForwardingError):
                forwarder.open([MappingRequest("TCP", 19132), MappingRequest("UDP", 19132)], "Easy Realms")
        self.assertEqual(calls[-1], ("DeletePortMapping", "TCP"))

    def test_refuses_permanent_router_mapping(self):
        forwarder = PortForwarder()
        service = GatewayService("urn:schemas-upnp-org:service:WANIPConnection:1", "http://192.168.1.1/control", "192.168.1.1")
        def soap(_, action, args):
            if action == "GetExternalIPAddress":
                return b"<Envelope />"
            raise PortForwardingError("UPnP error 725")
        with patch.object(forwarder, "discover", return_value=service), patch.object(
            forwarder, "internal_ip", return_value="192.168.1.50"
        ), patch.object(forwarder, "_soap", side_effect=soap):
            with self.assertRaisesRegex(PortForwardingError, "refused"):
                forwarder.open([MappingRequest("TCP", 25565)], "Easy Realms")

    def test_renewal_keeps_a_temporary_lease(self):
        forwarder = PortForwarder()
        service = GatewayService("urn:schemas-upnp-org:service:WANIPConnection:1", "http://192.168.1.1/control", "192.168.1.1")
        mapping = ActiveMapping(service, "TCP", 25565, "192.168.1.50")
        current = b'<Envelope><NewInternalPort>25565</NewInternalPort><NewInternalClient>192.168.1.50</NewInternalClient><NewPortMappingDescription>Easy Realms</NewPortMappingDescription></Envelope>'
        with patch.object(forwarder, "_soap", side_effect=[current, b""]) as soap:
            forwarder.renew([mapping])
        arguments = soap.call_args_list[-1].args[2]
        self.assertEqual(arguments["NewLeaseDuration"], 600)
        self.assertNotEqual(arguments["NewLeaseDuration"], 0)

    def test_renewal_refuses_to_overwrite_someone_elses_mapping(self):
        forwarder = PortForwarder()
        service = GatewayService("urn:schemas-upnp-org:service:WANIPConnection:1", "http://192.168.1.1/control", "192.168.1.1")
        mapping = ActiveMapping(service, "TCP", 25565, "192.168.1.50")
        foreign = b'<Envelope><NewInternalPort>25565</NewInternalPort><NewInternalClient>192.168.1.99</NewInternalClient><NewPortMappingDescription>Other app</NewPortMappingDescription></Envelope>'
        with patch.object(forwarder, "_soap", return_value=foreign) as soap:
            with self.assertRaisesRegex(PortForwardingError, "no longer belongs"):
                forwarder.renew([mapping])
        self.assertEqual(soap.call_count, 1)

    def test_cleanup_leaves_foreign_mapping_untouched(self):
        forwarder = PortForwarder()
        service = GatewayService("urn:schemas-upnp-org:service:WANIPConnection:1", "http://192.168.1.1/control", "192.168.1.1")
        mapping = ActiveMapping(service, "TCP", 25565, "192.168.1.50")
        foreign = b'<Envelope><NewInternalPort>25565</NewInternalPort><NewInternalClient>192.168.1.99</NewInternalClient><NewPortMappingDescription>Other app</NewPortMappingDescription></Envelope>'
        with patch.object(forwarder, "_soap", return_value=foreign) as soap:
            with self.assertRaisesRegex(PortForwardingError, "left untouched"):
                forwarder.close([mapping])
        self.assertEqual(soap.call_count, 1)


if __name__ == "__main__":
    unittest.main()
