import ipaddress
import json
import shutil
import re
import socket
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

from .models import CameraDevice


WS_DISCOVERY_ADDR = "239.255.255.250"
WS_DISCOVERY_PORT = 3702
ONVIF_SERVICE_PORTS = (80, 5000, 8899, 8080, 2000)
OUI_LOOKUP_PATH = Path(__file__).resolve().parent.parent / "latest_oui_lookup.json"
CAMERA_VENDOR_KEYWORDS = (
    "axis",
    "bosch",
    "cp plus",
    "dahua",
    "ezviz",
    "foscam",
    "geovision",
    "hikvision",
    "hiwatch",
    "honeywell",
    "imou",
    "jovision",
    "jvt",
    "longse",
    "milesight",
    "mobotix",
    "onvif",
    "panasonic",
    "reolink",
    "sony",
    "tapo",
    "tiandy",
    "tp-link",
    "tuya",
    "v380",
    "topsee",
    "juanvision",
    "uniview",
    "unv",
    "vivotek",
    "wanscam",
    "xmeye",
    "yoosee",
    "zavio",
)
ONVIF_DEVICE_SERVICE_PATHS = (
    "/onvif/device_service",
    "/onvif/device_service/",
)
ONVIF_PROBE_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
  <s:Body>
    <GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/>
  </s:Body>
</s:Envelope>"""


def discover_onvif(timeout=3.0):
    message_id = uuid.uuid4()
    probe = f"""<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
 xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{message_id}</w:MessageID>
    <w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </e:Body>
</e:Envelope>"""

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    except OSError:
        return []

    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)

    try:
        sock.sendto(probe.encode("utf-8"), (WS_DISCOVERY_ADDR, WS_DISCOVERY_PORT))
        devices = {}
        while True:
            try:
                data, sender = sock.recvfrom(65535)
            except socket.timeout:
                break

            device = parse_onvif_response(data, sender[0])
            existing = devices.get(device.ip)
            if existing:
                existing.onvif_found = True
                if existing.manufacturer == "Unknown":
                    existing.manufacturer = device.manufacturer
                if existing.model == "Unknown":
                    existing.model = device.model
            else:
                devices[device.ip] = device
        return list(devices.values())
    except OSError:
        return []
    finally:
        sock.close()


def parse_onvif_response(data, sender_ip):
    text = data.decode("utf-8", errors="ignore")
    xaddr = _first_text_by_local_name(text, "XAddrs")
    scopes = _first_text_by_local_name(text, "Scopes")

    ip = sender_ip
    if xaddr:
        parsed = urlparse(xaddr.split()[0])
        if parsed.hostname:
            ip = parsed.hostname

    manufacturer, model = parse_scopes(scopes)
    return CameraDevice(
        ip=ip,
        manufacturer=manufacturer,
        model=model,
        xaddr=xaddr or "",
        onvif_found=True,
    )


def parse_scopes(scopes):
    manufacturer = "Unknown"
    model = "Unknown"
    if not scopes:
        return manufacturer, model

    for item in scopes.split():
        clean = item.rsplit("/", 1)[-1].replace("%20", " ").strip()
        lower = item.lower()
        if "/hardware/" in lower and clean:
            model = clean
        elif "/name/" in lower and clean:
            manufacturer = clean

    return manufacturer, model


def _first_text_by_local_name(xml_text, local_name):
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        match = re.search(fr"<[^>]*{local_name}[^>]*>(.*?)</[^>]*{local_name}>", xml_text, re.S)
        return match.group(1).strip() if match else ""

    for elem in root.iter():
        if elem.tag.rsplit("}", 1)[-1] == local_name:
            return (elem.text or "").strip()
    return ""


def is_tcp_open(ip, port=554, timeout=0.6):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return False

    sock.settimeout(timeout)
    try:
        return sock.connect_ex((str(ip), port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def scan_rtsp_subnet(subnet, port=554, workers=128):
    network = ipaddress.ip_network(subnet, strict=False)
    found = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(is_tcp_open, ip, port): str(ip) for ip in network.hosts()}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                if future.result():
                    found.append(CameraDevice(ip=ip, rtsp_open=True))
            except OSError:
                pass
    return found


def arp_scan_subnet(subnet=None, timeout=45):
    if not shutil.which("arp-scan"):
        return [], "arp-scan not installed"

    command = ["arp-scan", "--plain"]
    if subnet:
        command.append(str(subnet))
    else:
        command.append("--localnet")

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], "arp-scan failed to run"

    devices = parse_arp_scan_output(result.stdout)
    if not devices and result.returncode != 0:
        message = (result.stderr or result.stdout or "arp-scan returned non-zero exit code").strip()
        return [], message
    return devices, ""


def nmap_discover_subnet(subnet=None, timeout=120):
    if not shutil.which("nmap"):
        return [], "nmap not installed"

    command = ["nmap", "-n", "-sn", "-PR", "-oX", "-"]
    if subnet:
        command.append(str(subnet))
    else:
        command.append("--localnet")

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], "nmap host discovery failed"

    devices = parse_nmap_discovery_output(result.stdout)
    if not devices and result.returncode != 0:
        message = (result.stderr or result.stdout or "nmap host discovery returned non-zero exit code").strip()
        return [], message
    return devices, ""


def parse_arp_scan_output(output):
    devices = {}
    for line in output.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2 or not _looks_like_ip(parts[0]) or not _looks_like_mac(parts[1]):
            continue

        ip, mac = parts[0], normalize_mac(parts[1])
        devices[ip] = CameraDevice(ip=ip, mac=mac)
    return list(devices.values())


def parse_nmap_discovery_output(xml_text):
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    devices = {}
    for host in root.findall("host"):
        status = host.find("status")
        if status is not None and status.attrib.get("state") not in (None, "up"):
            continue

        ip = ""
        mac = ""
        manufacturer = "Unknown"
        for address in host.findall("address"):
            addr_type = (address.attrib.get("addrtype") or "").lower()
            addr = address.attrib.get("addr") or ""
            if addr_type == "ipv4" and not ip:
                ip = addr
            elif addr_type == "mac" and not mac:
                mac = normalize_mac(addr)
                manufacturer = address.attrib.get("vendor") or manufacturer

        if not ip:
            continue

        devices[ip] = CameraDevice(ip=ip, mac=mac, manufacturer=manufacturer)

    return list(devices.values())


def read_system_arp_cache():
    import sys
    arp_cache = {}

    # 1. On Linux, try reading /proc/net/arp first (fastest, standard on Linux)
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/net/arp", "r") as f:
                lines = f.readlines()
                for line in lines[1:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        ip = parts[0]
                        mac = parts[3]
                        if mac and mac != "00:00:00:00:00:00" and len(mac) == 17:
                            arp_cache[ip] = mac
        except Exception:
            pass

    # 2. On Windows, macOS, or as a Linux fallback, try parsing 'arp -a'
    if not arp_cache:
        try:
            result = subprocess.run(
                ["arp", "-a"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    ip = None
                    mac = None
                    for part in parts:
                        clean_part = part.strip("()")
                        if _looks_like_ip(clean_part):
                            ip = clean_part
                        elif _looks_like_mac(clean_part):
                            mac = clean_part
                    if ip and mac and mac != "00:00:00:00:00:00":
                        arp_cache[ip] = mac
        except Exception:
            pass

    # 3. On Linux, try parsing 'ip neigh show' as a final fallback
    if not arp_cache and sys.platform.startswith("linux"):
        try:
            result = subprocess.run(
                ["ip", "neigh", "show"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 4:
                        ip = parts[0]
                        try:
                            lladdr_idx = parts.index("lladdr")
                            if lladdr_idx + 1 < len(parts):
                                mac = parts[lladdr_idx + 1]
                                if mac and mac != "00:00:00:00:00:00" and len(mac) == 17:
                                    arp_cache[ip] = mac
                        except ValueError:
                            continue
        except Exception:
            pass

    return arp_cache


def resolve_macs_from_system_cache(devices):
    arp_cache = read_system_arp_cache()
    for device in devices:
        if not device.mac or device.mac == "00:00:00:00:00:00":
            mac = arp_cache.get(device.ip)
            if mac:
                device.mac = normalize_mac(mac)


def enrich_devices_from_oui(devices, oui_lookup=None):
    lookup = oui_lookup if oui_lookup is not None else load_oui_lookup()
    for device in devices:
        vendor = lookup_oui_vendor(device.mac, lookup)
        if vendor:
            device.manufacturer = vendor


def load_oui_lookup(path=OUI_LOOKUP_PATH):
    try:
        with open(path, "r", encoding="utf-8") as file_obj:
            return json.load(file_obj)
    except (OSError, json.JSONDecodeError):
        return {}


def lookup_oui_vendor(mac, oui_lookup):
    normalized = normalize_mac(mac)
    if not normalized:
        return ""

    oui = "-".join(normalized.split(":")[:3]).upper()
    return oui_lookup.get(oui) or oui_lookup.get(oui.replace("-", ":")) or ""


def filter_camera_candidates(devices):
    candidates = []
    for device in devices:
        if device.manufacturer == "Unknown" or is_camera_vendor(device.manufacturer):
            candidates.append(device)
    return candidates


def is_camera_vendor(vendor):
    text = (vendor or "").lower()
    return any(keyword in text for keyword in CAMERA_VENDOR_KEYWORDS)


def nmap_scan_all_ports_for_devices(devices, workers=8, timeout=240, progress_callback=None, start_pct=40, end_pct=80):
    if not devices or not shutil.which("nmap"):
        return

    max_workers = min(workers, max(1, len(devices)))
    total = len(devices)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(nmap_scan_all_ports, device.ip, timeout=timeout): device
            for device in devices
        }
        for idx, future in enumerate(as_completed(futures), start=1):
            device = futures[future]
            try:
                ports = future.result()
            except OSError:
                continue
            device.open_ports = ports
            device.rtsp_open = 554 in ports
            if progress_callback:
                pct = start_pct + int((idx / total) * (end_pct - start_pct))
                progress_callback(pct, f"Scanned ports for {device.ip} ({idx}/{total})")


def nmap_scan_all_ports(ip, timeout=240):
    command = ["nmap", "-Pn", "-p-", "--open", "-oX", "-", str(ip)]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    return parse_nmap_open_ports(result.stdout)


def parse_nmap_open_ports(xml_text):
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    ports = []
    for port_elem in root.iter("port"):
        state_elem = port_elem.find("state")
        if state_elem is None or state_elem.attrib.get("state") != "open":
            continue
        try:
            ports.append(int(port_elem.attrib["portid"]))
        except (KeyError, ValueError):
            continue
    return sorted(set(ports))


def probe_onvif_service(ip, ports=ONVIF_SERVICE_PORTS, timeout=1.0):
    for port in ports:
        for path in ONVIF_DEVICE_SERVICE_PATHS:
            if _probe_onvif_endpoint(ip, port, path, timeout=timeout):
                return CameraDevice(
                    ip=str(ip),
                    manufacturer=_manufacturer_hint_from_onvif_port(port),
                    model=f"ONVIF port {port}",
                    xaddr=f"http://{ip}:{port}{path}",
                    onvif_found=True,
                )
    return None


def _probe_onvif_endpoint(ip, port, path, timeout=1.0):
    body = ONVIF_PROBE_BODY.encode("utf-8")
    request = "\r\n".join(
        [
            f"POST {path} HTTP/1.1",
            f"Host: {ip}:{port}",
            "User-Agent: camera-autodetect",
            "Content-Type: application/soap+xml; charset=utf-8",
            f"Content-Length: {len(body)}",
            "Connection: close",
            "",
            "",
        ]
    ).encode("utf-8") + body

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        return False

    sock.settimeout(timeout)
    try:
        sock.connect((str(ip), port))
        sock.sendall(request)
        response = sock.recv(4096).decode("utf-8", errors="ignore")
    except OSError:
        return False
    finally:
        sock.close()

    lower = response.lower()
    if "www-authenticate" in lower and ("onvif" in lower or "digest" in lower or "basic" in lower):
        return True
    return (
        "http/1." in lower
        and any(marker in lower for marker in ("getsystemdateandtimeresponse", "onvif", "soap"))
        and "404" not in lower.split("\r\n", 1)[0]
    )


def scan_onvif_for_devices(devices, workers=64):
    targets = [device for device in devices if not device.onvif_found]
    if not targets:
        return

    max_workers = min(workers, max(1, len(targets)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(probe_onvif_service, device.ip, _onvif_probe_ports(device)): device
            for device in targets
        }
        for future in as_completed(futures):
            device = futures[future]
            try:
                onvif_device = future.result()
            except OSError:
                continue
            if not onvif_device:
                continue

            device.onvif_found = True
            device.xaddr = onvif_device.xaddr
            if device.manufacturer == "Unknown":
                device.manufacturer = onvif_device.manufacturer
            if device.model == "Unknown":
                device.model = onvif_device.model


def _onvif_probe_ports(device):
    if not device.open_ports:
        return ONVIF_SERVICE_PORTS

    ports = [port for port in device.open_ports if 1 <= port <= 65535]
    for port in ONVIF_SERVICE_PORTS:
        if port not in ports:
            ports.append(port)
    return ports


def scan_rtsp_for_devices(devices, rtsp_port=554, workers=64):
    targets = [device for device in devices if rtsp_port not in device.open_ports and not device.rtsp_open]
    if not targets:
        return

    max_workers = min(workers, max(1, len(targets)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(is_tcp_open, device.ip, rtsp_port): device for device in targets}
        for future in as_completed(futures):
            device = futures[future]
            try:
                device.rtsp_open = future.result()
            except OSError:
                continue
            if device.rtsp_open and rtsp_port not in device.open_ports:
                device.open_ports.append(rtsp_port)
                device.open_ports.sort()


def _manufacturer_hint_from_onvif_port(port):
    return {
        80: "Generic",
        5000: "YOOSEE",
        8899: "V380/XMEYE",
        8080: "Tiandy",
        2000: "JVT",
    }.get(port, "Unknown")


def scan_network(subnet=None, rtsp_port=554, progress_callback=None):
    devices = {}
    source_note = ""

    if progress_callback:
        progress_callback(5, "Starting network scan...")

    if progress_callback:
        progress_callback(10, "Attempting ARP subnet scan...")
    arp_devices, arp_error = arp_scan_subnet(subnet)
    if arp_devices:
        enrich_devices_from_oui(arp_devices)
        candidates = filter_camera_candidates(arp_devices)
        if progress_callback:
            progress_callback(30, f"Found {len(candidates)} candidates via ARP. Scanning ports...")
        nmap_scan_all_ports_for_devices(candidates, progress_callback=progress_callback, start_pct=30, end_pct=80)
        devices.update({device.ip: device for device in candidates})
    elif subnet:
        if progress_callback:
            progress_callback(15, "Running host discovery via Nmap...")
        nmap_devices, nmap_error = nmap_discover_subnet(subnet)
        if nmap_devices:
            resolve_macs_from_system_cache(nmap_devices)
            enrich_devices_from_oui(nmap_devices)
            candidates = filter_camera_candidates(nmap_devices)
            if progress_callback:
                progress_callback(30, f"Found {len(candidates)} candidates via Nmap. Scanning ports...")
            nmap_scan_all_ports_for_devices(candidates, progress_callback=progress_callback, start_pct=30, end_pct=80)
            devices.update({device.ip: device for device in candidates})
            source_note = "fallback to nmap discovery"
            if arp_error:
                source_note = f"{arp_error}; {source_note}"
        else:
            if progress_callback:
                progress_callback(20, "Nmap failed. Running RTSP TCP port sweep...")
            rtsp_devices = scan_rtsp_subnet(subnet, rtsp_port)
            resolve_macs_from_system_cache(rtsp_devices)
            enrich_devices_from_oui(rtsp_devices)
            candidates = filter_camera_candidates(rtsp_devices)
            if progress_callback:
                progress_callback(40, f"Found {len(candidates)} RTSP candidates. Scanning ports...")
            nmap_scan_all_ports_for_devices(candidates, progress_callback=progress_callback, start_pct=40, end_pct=80)
            devices.update({device.ip: device for device in candidates})
            parts = [part for part in (arp_error, nmap_error) if part]
            if parts:
                source_note = "; ".join(parts)

    if progress_callback:
        progress_callback(80, "Running ONVIF WS-Discovery...")
    for onvif_device in discover_onvif():
        device = devices.get(onvif_device.ip)
        if device:
            device.onvif_found = True
            device.xaddr = onvif_device.xaddr or device.xaddr
            device.mac = device.mac or onvif_device.mac
            if device.manufacturer == "Unknown":
                device.manufacturer = onvif_device.manufacturer
            if device.model == "Unknown":
                device.model = onvif_device.model
        else:
            devices[onvif_device.ip] = onvif_device

    # Final pass to resolve MACs and OUI for any devices still missing them (e.g. from ONVIF discovery)
    if progress_callback:
        progress_callback(85, "Resolving MAC addresses and querying OUI...")
    resolve_macs_from_system_cache(devices.values())
    enrich_devices_from_oui(devices.values())

    if progress_callback:
        progress_callback(90, "Probing RTSP and ONVIF services...")
    scan_rtsp_for_devices(devices.values(), rtsp_port=rtsp_port)
    scan_onvif_for_devices(devices.values())

    if progress_callback:
        progress_callback(100, "Scan complete")

    return sorted(devices.values(), key=_sort_key), source_note


def _sort_key(device):
    try:
        return (0, ipaddress.ip_address(device.ip))
    except ValueError:
        return (1, device.ip)


def normalize_mac(mac):
    clean = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    if len(clean) < 12:
        return ""
    pairs = [clean[index : index + 2].upper() for index in range(0, 12, 2)]
    return ":".join(pairs)


def _looks_like_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _looks_like_mac(value):
    return bool(re.fullmatch(r"(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}", value))
