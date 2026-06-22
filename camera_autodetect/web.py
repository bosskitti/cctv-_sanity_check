import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .brands import get_handler
from .models import CameraCredentials, CameraDevice
from .rtsp_client import verify_rtsp_credentials, check_rtsp_signal
from .scanner import scan_network


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
CACHE_FILE = BASE_DIR / "latest_scan_cache.json"
DASHBOARD_FILE = BASE_DIR / "dashboard_devices.json"

SCAN_STATUS = {"percentage": 0, "message": "Ready", "status": "idle"}


class CameraApiHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/api/scan-status":
            self.send_json(SCAN_STATUS)
            return
        if route == "/api/dashboard/list":
            self.handle_dashboard_list()
            return
        if route == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        route = urlparse(self.path).path
        try:
            if route == "/api/scan":
                self.handle_scan()
            elif route == "/api/verify-rtsp":
                self.handle_verify_rtsp()
            elif route == "/api/check-signal":
                self.handle_check_signal()
            elif route == "/api/update-device-rtsp":
                self.handle_update_device_rtsp()
            elif route == "/api/dashboard/add":
                self.handle_dashboard_add()
            elif route == "/api/dashboard/remove":
                self.handle_dashboard_remove()
            elif route == "/api/dashboard/refresh":
                self.handle_dashboard_refresh()
            else:
                self.send_json({"error": "not found"}, status=404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def handle_scan(self):
        global SCAN_STATUS
        payload = self.read_json()
        subnet = payload.get("subnet") or None
        rtsp_port = int(payload.get("rtsp_port") or 554)
        use_cache = bool(payload.get("use_cache", True))
        filter_cameras = bool(payload.get("filter_cameras", True))

        import time
        from datetime import datetime

        # Reset progress
        SCAN_STATUS = {"percentage": 0, "message": "Starting scan...", "status": "scanning"}

        # Try loading from cache file
        if use_cache and CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                if (
                    cache_data.get("subnet") == subnet
                    and cache_data.get("rtsp_port") == rtsp_port
                    and cache_data.get("filter_cameras", True) == filter_cameras
                ):
                    timestamp = cache_data.get("timestamp", 0)
                    formatted_time = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
                    cached_note = cache_data.get("scan_note", "")
                    scan_note = f"(Loaded from cache: {formatted_time})"
                    if cached_note:
                        scan_note += f" {cached_note}"
                    SCAN_STATUS = {"percentage": 100, "message": "Scan loaded from cache", "status": "idle"}
                    devices_out = []
                    for raw in cache_data.get("devices", []):
                        dev_obj = device_from_dict(raw)
                        cached_rtsp_url = raw.get("rtsp_url", "")
                        devices_out.append(device_to_dict(dev_obj, rtsp_url=cached_rtsp_url))

                    self.send_json(
                        {
                            "devices": devices_out,
                            "scan_note": scan_note.strip(),
                        }
                    )
                    return
            except Exception:
                pass

        # Progress callback function
        def progress_callback(pct, msg):
            global SCAN_STATUS
            SCAN_STATUS["percentage"] = pct
            SCAN_STATUS["message"] = msg

        # Fresh scan
        devices, scan_note = scan_network(
            subnet=subnet,
            rtsp_port=rtsp_port,
            progress_callback=progress_callback,
            filter_cameras=filter_cameras,
        )
        device_dicts = [device_to_dict(device) for device in devices]

        # Save to cache file
        try:
            cache_data = {
                "subnet": subnet,
                "rtsp_port": rtsp_port,
                "filter_cameras": filter_cameras,
                "timestamp": time.time(),
                "scan_note": scan_note,
                "devices": device_dicts,
            }
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        SCAN_STATUS = {"percentage": 100, "message": "Scan complete", "status": "idle"}

        self.send_json(
            {
                "devices": device_dicts,
                "scan_note": scan_note,
            }
        )

    def handle_verify_rtsp(self):
        payload = self.read_json()
        channel = int(payload.get("channel") or 1)
        devices_in = [device_from_dict(raw) for raw in payload.get("devices", [])]

        from concurrent.futures import ThreadPoolExecutor

        def check_device(device):
            if not device.credentials.has_rtsp:
                device.rtsp_auth_status = "NO_CREDENTIAL"
                return device_to_dict(device, include_rtsp_url=False)
            if not device.rtsp_open:
                device.rtsp_auth_status = "PORT_CLOSED"
                return device_to_dict(device, include_rtsp_url=False)

            handler = get_handler(device.brand_key)
            port = 554
            if 554 in device.open_ports:
                port = 554
            elif device.open_ports:
                port = device.open_ports[0]

            rtsp_url = handler.build_rtsp_url(
                device.ip,
                device.credentials.rtsp_user,
                device.credentials.rtsp_password,
                channel=channel,
                subtype=0,
                port=port,
            )

            traffic = check_rtsp_signal(
                device.ip,
                port,
                rtsp_url,
                device.credentials.rtsp_user,
                device.credentials.rtsp_password,
            )
            if isinstance(traffic, int):
                device.rtsp_auth_status = "ONLINE" if traffic > 10000 else "VIDEO_LOSS"
            else:
                device.rtsp_auth_status = traffic

            return device_to_dict(device, rtsp_url=rtsp_url)

        with ThreadPoolExecutor(max_workers=16) as executor:
            devices_out = list(executor.map(check_device, devices_in))

        # Save updated devices (with credentials and auth status) to cache file
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                updated_map = {d["ip"]: d for d in devices_out}
                for cached_dev in cache_data.get("devices", []):
                    ip = cached_dev.get("ip")
                    if ip in updated_map:
                        cached_dev["credentials"] = updated_map[ip]["credentials"]
                        cached_dev["rtsp_auth_status"] = updated_map[ip]["rtsp_auth_status"]
                        cached_dev["rtsp_url"] = updated_map[ip].get("rtsp_url", "")
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        self.send_json({"devices": devices_out})

    def handle_check_signal(self):
        payload = self.read_json()
        ip = payload.get("ip")
        port = int(payload.get("port") or 554)
        brand_key = payload.get("brand_key", "generic")
        custom_rtsp_url = payload.get("custom_rtsp_url")

        credentials = payload.get("credentials") or {}
        user = credentials.get("rtsp_user") or ""
        password = credentials.get("rtsp_password") or ""

        handler = get_handler(brand_key)

        from concurrent.futures import ThreadPoolExecutor

        def check_chan(channel_id):
            if custom_rtsp_url:
                rtsp_url = adjust_channel_in_url(custom_rtsp_url, channel_id)
            else:
                rtsp_url = handler.build_rtsp_url(ip, user, password, channel=channel_id, subtype=0, port=port)

            chan_user = user
            chan_pass = password
            parsed = urlparse(rtsp_url)
            if parsed.username:
                chan_user = parsed.username
            if parsed.password:
                chan_pass = parsed.password

            traffic = check_rtsp_signal(ip, port, rtsp_url, chan_user, chan_pass)

            res = {"channel": channel_id, "rtsp_url": rtsp_url}
            if isinstance(traffic, int):
                res["status"] = "ONLINE" if traffic > 10000 else "VIDEO_LOSS"
                res["bytes"] = traffic
            else:
                res["status"] = "ERROR"
                res["error"] = str(traffic)
            return res

        # Run channel 1 to 8 checks in parallel
        with ThreadPoolExecutor(max_workers=8) as executor:
            channel_results = list(executor.map(check_chan, range(1, 9)))

        # Default URL shown in table is channel 1
        rtsp_url_default = custom_rtsp_url if custom_rtsp_url else handler.build_rtsp_url(ip, user, password, channel=1, subtype=0, port=port)

        self.send_json({
            "rtsp_url": rtsp_url_default,
            "channels": channel_results
        })

    def handle_update_device_rtsp(self):
        payload = self.read_json()
        ip = payload.get("ip")
        rtsp_url = payload.get("rtsp_url")
        rtsp_url_manual = bool(payload.get("rtsp_url_manual", True))

        # Update in cache
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                for cached_dev in cache_data.get("devices", []):
                    if cached_dev.get("ip") == ip:
                        cached_dev["rtsp_url"] = rtsp_url
                        cached_dev["rtsp_url_manual"] = rtsp_url_manual
                        # Extract credentials if embedded in manual URL
                        parsed = urlparse(rtsp_url)
                        if parsed.username or parsed.password:
                            creds = cached_dev.get("credentials") or {}
                            if parsed.username:
                                creds["rtsp_user"] = parsed.username
                            if parsed.password:
                                creds["rtsp_password"] = parsed.password
                            cached_dev["credentials"] = creds
                with open(CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache_data, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
        self.send_json({"status": "success"})

    def handle_dashboard_add(self):
        payload = self.read_json()
        ip = payload.get("ip")
        if not ip:
            self.send_json({"error": "missing ip"}, status=400)
            return

        devices = self.read_dashboard_devices()
        exists = False
        for dev in devices:
            if dev.get("ip") == ip:
                dev.update(payload)
                exists = True
                break
        if not exists:
            devices.append(payload)

        self.write_dashboard_devices(devices)
        self.send_json({"status": "success"})

    def handle_dashboard_remove(self):
        payload = self.read_json()
        ip = payload.get("ip")
        if not ip:
            self.send_json({"error": "missing ip"}, status=400)
            return

        devices = self.read_dashboard_devices()
        devices = [dev for dev in devices if dev.get("ip") != ip]
        self.write_dashboard_devices(devices)
        self.send_json({"status": "success"})

    def handle_dashboard_list(self):
        devices = self.read_dashboard_devices()
        self.send_json({"devices": devices})

    def handle_dashboard_refresh(self):
        devices = self.read_dashboard_devices()

        from concurrent.futures import ThreadPoolExecutor

        def refresh_device(device):
            ip = device.get("ip")
            port = 554
            open_ports = device.get("open_ports") or []
            if 554 in open_ports:
                port = 554
            elif open_ports:
                port = open_ports[0]

            brand_key = device.get("brand_key", "generic")
            custom_rtsp_url = device.get("rtsp_url") if device.get("rtsp_url_manual") else None

            credentials = device.get("credentials") or {}
            user = credentials.get("rtsp_user") or ""
            password = credentials.get("rtsp_password") or ""

            handler = get_handler(brand_key)

            def check_chan(channel_id):
                if custom_rtsp_url:
                    rtsp_url = adjust_channel_in_url(custom_rtsp_url, channel_id)
                else:
                    rtsp_url = handler.build_rtsp_url(ip, user, password, channel=channel_id, subtype=0, port=port)

                chan_user = user
                chan_pass = password
                parsed = urlparse(rtsp_url)
                if parsed.username:
                    chan_user = parsed.username
                if parsed.password:
                    chan_pass = parsed.password

                traffic = check_rtsp_signal(ip, port, rtsp_url, chan_user, chan_pass)
                res = {"channel": channel_id, "rtsp_url": rtsp_url}
                if isinstance(traffic, int):
                    res["status"] = "ONLINE" if traffic > 10000 else "VIDEO_LOSS"
                    res["bytes"] = traffic
                else:
                    res["status"] = "ERROR"
                    res["error"] = str(traffic)
                return res

            with ThreadPoolExecutor(max_workers=8) as executor:
                channel_results = list(executor.map(check_chan, range(1, 9)))

            device["channels_status"] = channel_results
            return device

        with ThreadPoolExecutor(max_workers=8) as executor:
            refreshed_devices = list(executor.map(refresh_device, devices))

        self.write_dashboard_devices(refreshed_devices)
        self.send_json({"devices": refreshed_devices})

    def read_dashboard_devices(self):
        if not DASHBOARD_FILE.exists():
            return []
        try:
            with open(DASHBOARD_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def write_dashboard_devices(self, devices):
        try:
            with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
                json.dump(devices, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def send_json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")


import re

def adjust_channel_in_url(url, channel_id):
    if not url:
        return url
    # Replace channel=X
    url = re.sub(r'([?&]channel=)\d+', r'\g<1>' + str(channel_id), url, flags=re.I)
    # Replace /chX/
    url = re.sub(r'(/ch)\d+(/)', r'\g<1>' + str(channel_id) + r'\g<2>', url, flags=re.I)
    # Replace /chX_
    url = re.sub(r'(/ch)\d+(_)', r'\g<1>' + str(channel_id) + r'\g<2>', url, flags=re.I)
    # Replace /live/chX
    url = re.sub(r'(/live/ch)\d+', r'\g<1>' + str(channel_id), url, flags=re.I)
    # Replace /onvifX
    url = re.sub(r'(/onvif)\d+', r'\g<1>' + str(channel_id), url, flags=re.I)
    return url


def device_to_dict(device, rtsp_url="", include_rtsp_url=True):
    handler = get_handler(device.brand_key)
    if not rtsp_url:
        if device.rtsp_url_manual and device.rtsp_url:
            rtsp_url = device.rtsp_url
        else:
            port = 554
            if 554 in device.open_ports:
                port = 554
            elif device.open_ports:
                port = device.open_ports[0]
            
            rtsp_url = handler.build_rtsp_url(
                device.ip,
                device.credentials.rtsp_user,
                device.credentials.rtsp_password,
                channel=1,
                subtype=0,
                port=port
            )

    data = {
        "ip": device.ip,
        "mac": device.mac,
        "manufacturer": device.manufacturer,
        "model": device.model,
        "brand_key": device.brand_key,
        "handler": handler.describe(device),
        "xaddr": device.xaddr,
        "onvif_found": device.onvif_found,
        "rtsp_open": device.rtsp_open,
        "open_ports": device.open_ports,
        "rtsp_auth_status": device.rtsp_auth_status,
        "rtsp_url_manual": device.rtsp_url_manual,
    }
    if include_rtsp_url:
        data["rtsp_url"] = rtsp_url
    return data


def device_from_dict(raw):
    credentials = raw.get("credentials") or {}
    return CameraDevice(
        ip=raw.get("ip", ""),
        mac=raw.get("mac") or "",
        manufacturer=raw.get("manufacturer") or "Unknown",
        model=raw.get("model") or "Unknown",
        xaddr=raw.get("xaddr") or "",
        onvif_found=bool(raw.get("onvif_found")),
        rtsp_open=bool(raw.get("rtsp_open")),
        open_ports=[int(port) for port in raw.get("open_ports") or []],
        rtsp_auth_status=raw.get("rtsp_auth_status") or "NOT_CHECKED",
        credentials=CameraCredentials(
            rtsp_user=credentials.get("rtsp_user") or "",
            rtsp_password=credentials.get("rtsp_password") or "",
            onvif_user=credentials.get("onvif_user") or "",
            onvif_password=credentials.get("onvif_password") or "",
        ),
        rtsp_url=raw.get("rtsp_url") or "",
        rtsp_url_manual=bool(raw.get("rtsp_url_manual")),
    )


def run(host="127.0.0.1", port=8000):
    server = ThreadingHTTPServer((host, port), CameraApiHandler)
    print(f"Camera Autodetect UI: http://{host}:{port}")
    server.serve_forever()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Camera Autodetect web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
