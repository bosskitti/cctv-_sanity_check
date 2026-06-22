import argparse
import getpass

from .brands import get_handler
from .models import CameraCredentials
from .rtsp_client import verify_rtsp_credentials
from .scanner import scan_network


def print_devices(devices, channel=1):
    if not devices:
        print("ไม่พบกล้องจาก ONVIF หรือ RTSP scan")
        return

    print("\nDetected cameras")
    print("-" * 156)
    print(
        f"{'#':<3} {'RTSP':<5} {'ONVIF':<6} {'RTSP Auth':<12} {'RTSP Cred':<9} {'ONVIF Cred':<10} "
        f"{'Brand':<12} {'IP':<15} {'MAC':<17} {'Ports':<18} {'Model':<20} Handler"
    )
    print("-" * 156)

    for index, device in enumerate(devices, start=1):
        handler = get_handler(device.brand_key)
        rtsp_state = "OPEN" if device.rtsp_open else "CLOSE"
        onvif_state = "YES" if device.onvif_found else "NO"
        rtsp_cred = "YES" if device.credentials.has_rtsp else "NO"
        onvif_cred = "YES" if device.credentials.has_onvif else "NO"
        print(
            f"{index:<3} {rtsp_state:<5} {onvif_state:<6} {device.rtsp_auth_status:<12} "
            f"{rtsp_cred:<9} {onvif_cred:<10} "
            f"{device.manufacturer[:12]:<12} {device.ip:<15} {device.mac[:17]:<17} "
            f"{format_ports(device.open_ports):<18} {device.model[:20]:<20} "
            f"{handler.describe(device)}"
        )

        if device.credentials.has_rtsp and device.rtsp_open:
            url = handler.build_rtsp_url(
                device.ip,
                device.credentials.rtsp_user,
                device.credentials.rtsp_password,
                channel=channel,
            )
            print(f"    RTSP: {url}")

        if device.credentials.has_onvif and device.xaddr:
            print(f"    ONVIF credential ready for: {device.xaddr}")


def build_global_credentials(args):
    rtsp_user = args.rtsp_user or args.user or ""
    rtsp_password = args.rtsp_password or args.password or ""
    onvif_user = args.onvif_user or args.user or rtsp_user
    onvif_password = args.onvif_password or args.password or rtsp_password

    if args.ask_password:
        if rtsp_user and not rtsp_password:
            rtsp_password = getpass.getpass("RTSP password: ")
        if onvif_user and not onvif_password:
            onvif_password = getpass.getpass("ONVIF password: ")

    return CameraCredentials(
        rtsp_user=rtsp_user,
        rtsp_password=rtsp_password,
        onvif_user=onvif_user,
        onvif_password=onvif_password,
    )


def apply_global_credentials(devices, credentials):
    for device in devices:
        device.credentials = CameraCredentials(
            rtsp_user=credentials.rtsp_user,
            rtsp_password=credentials.rtsp_password,
            onvif_user=credentials.onvif_user,
            onvif_password=credentials.onvif_password,
        )


def prompt_credentials_per_device(devices, defaults):
    print("\nCredential setup")
    print("Enter = ใช้ค่า default/ค่าก่อนหน้า, '-' = เว้นว่าง")

    last_rtsp_user = defaults.rtsp_user
    last_rtsp_password = defaults.rtsp_password
    last_onvif_user = defaults.onvif_user
    last_onvif_password = defaults.onvif_password

    for index, device in enumerate(devices, start=1):
        print(f"\n[{index}] {device.ip} | {device.manufacturer} | {device.model}")

        rtsp_user = prompt_text("RTSP user", last_rtsp_user)
        rtsp_password = prompt_password("RTSP password", last_rtsp_password)

        same = input("ใช้ credential ชุดเดียวกันกับ ONVIF ไหม? [Y/n]: ").strip().lower()
        if same in ("", "y", "yes"):
            onvif_user = rtsp_user
            onvif_password = rtsp_password
        else:
            onvif_user = prompt_text("ONVIF user", last_onvif_user)
            onvif_password = prompt_password("ONVIF password", last_onvif_password)

        device.credentials = CameraCredentials(
            rtsp_user=rtsp_user,
            rtsp_password=rtsp_password,
            onvif_user=onvif_user,
            onvif_password=onvif_password,
        )

        last_rtsp_user = rtsp_user or last_rtsp_user
        last_rtsp_password = rtsp_password or last_rtsp_password
        last_onvif_user = onvif_user or last_onvif_user
        last_onvif_password = onvif_password or last_onvif_password


def prompt_text(label, default):
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    if value == "-":
        return ""
    return value or default


def prompt_password(label, default):
    suffix = " [saved]" if default else ""
    value = getpass.getpass(f"{label}{suffix}: ")
    if value == "-":
        return ""
    return value or default


def verify_rtsp_for_devices(devices, channel):
    for device in devices:
        if not device.rtsp_open:
            device.rtsp_auth_status = "PORT_CLOSED"
            continue
        if not device.credentials.has_rtsp:
            device.rtsp_auth_status = "NO_CREDENTIAL"
            continue

        handler = get_handler(device.brand_key)
        rtsp_url = handler.build_rtsp_url(
            device.ip,
            device.credentials.rtsp_user,
            device.credentials.rtsp_password,
            channel=channel,
        )
        print(f"ตรวจ RTSP auth: {device.ip} ... ", end="", flush=True)
        device.rtsp_auth_status = verify_rtsp_credentials(
            rtsp_url,
            device.credentials.rtsp_user,
            device.credentials.rtsp_password,
        )
        print(device.rtsp_auth_status)


def format_ports(ports):
    if not ports:
        return "-"
    text = ",".join(str(port) for port in sorted(ports)[:6])
    if len(ports) > 6:
        text += ",..."
    return text


def main():
    parser = argparse.ArgumentParser(description="ONVIF + RTSP camera autodetect")
    parser.add_argument("--scan", action="store_true", help="run network scan")
    parser.add_argument("--subnet", help="optional subnet for RTSP scan, e.g. 192.168.1.0/24")
    parser.add_argument("--credentials", choices=("none", "global", "per-device"), default="none")
    parser.add_argument("--user", help="default username for both RTSP and ONVIF")
    parser.add_argument("--password", help="default password for both RTSP and ONVIF")
    parser.add_argument("--rtsp-user", help="default RTSP username")
    parser.add_argument("--rtsp-password", help="default RTSP password")
    parser.add_argument("--onvif-user", help="default ONVIF username")
    parser.add_argument("--onvif-password", help="default ONVIF password")
    parser.add_argument("--ask-password", action="store_true", help="prompt for missing global passwords securely")
    parser.add_argument("--verify-rtsp", action="store_true", help="test RTSP DESCRIBE with configured credentials")
    parser.add_argument("--channel", type=int, default=1, help="camera channel for generated RTSP URL")
    args = parser.parse_args()

    if not args.scan:
        parser.print_help()
        return

    devices, scan_note = scan_network(subnet=args.subnet)
    credentials = build_global_credentials(args)

    if args.credentials == "global" or has_any_credentials(credentials):
        apply_global_credentials(devices, credentials)

    if args.credentials == "per-device":
        prompt_credentials_per_device(devices, credentials)

    if args.verify_rtsp:
        verify_rtsp_for_devices(devices, args.channel)

    if scan_note:
        print(f"Scan note: {scan_note}")
    print_devices(devices, channel=args.channel)


def has_any_credentials(credentials):
    return any(
        (
            credentials.rtsp_user,
            credentials.rtsp_password,
            credentials.onvif_user,
            credentials.onvif_password,
        )
    )


if __name__ == "__main__":
    main()
