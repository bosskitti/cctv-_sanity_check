import json
import socket
import time
import re
from pathlib import Path

# Import helper libraries from camera_autodetect
from camera_autodetect.brands import get_handler
from camera_autodetect.rtsp_client import parse_auth_challenge, build_auth_header, status_code, strip_url_credentials

CACHE_FILE = Path(__file__).resolve().parent / "latest_scan_cache.json"

def check_rtsp_signal(ip, port, rtsp_url, user, password):
    request_url = strip_url_credentials(rtsp_url)
    
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.5)
    
    try:
        s.connect((ip, port))
    except Exception:
        return "ERROR_CONN"

    # Step 1: DESCRIBE (Handshake)
    req1 = f"DESCRIBE {request_url} RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: Lavf58.29.100\r\nAccept: application/sdp\r\n\r\n"
    s.send(req1.encode())
    try:
        res1 = s.recv(2048).decode('utf-8', errors='ignore')
    except Exception:
        s.close()
        return "TIMEOUT"
        
    code = status_code(res1)
    auth_header = None
    
    if code == 401:
        challenge = parse_auth_challenge(res1)
        if not challenge:
            s.close()
            return "AUTH_REQUIRED"
        auth_header = build_auth_header(challenge, user, password, "DESCRIBE", request_url)
        if not auth_header:
            s.close()
            return "AUTH_UNSUPPORTED"
            
        req2 = f"DESCRIBE {request_url} RTSP/1.0\r\nCSeq: 2\r\nUser-Agent: Lavf58.29.100\r\nAuthorization: {auth_header}\r\nAccept: application/sdp\r\n\r\n"
        s.send(req2.encode())
        try:
            res2 = s.recv(2048).decode('utf-8', errors='ignore')
        except Exception:
            s.close()
            return "TIMEOUT"
        code2 = status_code(res2)
        if code2 != 200:
            s.close()
            return f"AUTH_FAILED_{code2}"
    elif code != 200:
        s.close()
        return f"DESCRIBE_FAILED_{code}"

    # Step 2: SETUP TCP Stream
    track = "trackID=0"
    control_match = re.search(r'control:(.*?)\r?\n', res1 if code == 200 else res2)
    if control_match:
        ctrl = control_match.group(1).strip()
        if ctrl and ctrl != "*" and not ctrl.startswith("rtsp://"):
            track = ctrl

    setup_url = f"{request_url}/{track}" if not track.startswith("rtsp://") else track
    
    req_setup = f"SETUP {setup_url} RTSP/1.0\r\nCSeq: 3\r\nUser-Agent: Lavf58.29.100\r\n"
    if auth_header:
        req_setup += f"Authorization: {auth_header}\r\n"
    req_setup += "Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n\r\n"
    
    s.send(req_setup.encode())
    try:
        res_setup = s.recv(2048).decode('utf-8', errors='ignore')
    except Exception:
        s.close()
        return "TIMEOUT"
        
    session_match = re.search(r'Session:\s*([;\w]+)', res_setup)
    if not session_match:
        s.close()
        return "SETUP_FAILED"
    session_id = session_match.group(1).split(';')[0]

    # Step 3: PLAY Stream
    req_play = f"PLAY {request_url} RTSP/1.0\r\nCSeq: 4\r\nUser-Agent: Lavf58.29.100\r\n"
    if auth_header:
        req_play += f"Authorization: {auth_header}\r\n"
    req_play += f"Session: {session_id}\r\n\r\n"
    
    s.send(req_play.encode())
    try:
        s.recv(2048)
    except Exception:
        s.close()
        return "TIMEOUT"
        
    # Step 4: Measure bytes
    total_bytes = 0
    start_time = time.time()
    s.settimeout(0.5)
    
    try:
        while time.time() - start_time < 1.0:
            data = s.recv(8192)
            if not data:
                break
            total_bytes += len(data)
    except socket.timeout:
        pass
        
    s.close()
    return total_bytes

def main():
    if not CACHE_FILE.exists():
        print(f"❌ ไม่พบไฟล์ cache ที่ {CACHE_FILE} กรุณาทำการสแกนกล้องผ่านหน้าเว็บก่อน")
        return

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
    except Exception as e:
        print(f"❌ ไม่สามารถอ่านไฟล์ cache ได้: {e}")
        return

    devices = cache_data.get("devices", [])
    if not devices:
        print("❌ ไม่พบอุปกรณ์กล้องในไฟล์ cache")
        return

    print("\n" + "="*80)
    print(" 📡 รายงานสัญญาณกล้อง IP/DVR เรียลไทม์ (Bitrate & Coaxial Status)")
    print("="*80)

    for device in devices:
        ip = device.get("ip")
        manufacturer = device.get("manufacturer", "Unknown")
        model = device.get("model", "Unknown")
        from camera_autodetect.models import CameraDevice
        dev_obj = CameraDevice(ip=ip, manufacturer=manufacturer, model=model)
        brand_key = dev_obj.brand_key
        
        # Check if the device has open RTSP ports
        ports = device.get("open_ports", [])
        rtsp_port = 554
        if 554 in ports:
            rtsp_port = 554
        elif ports:
            rtsp_port = ports[0]
            
        credentials = device.get("credentials") or {}
        user = credentials.get("rtsp_user") or ""
        password = credentials.get("rtsp_password") or ""
        
        print(f"\n🎥 อุปกรณ์: {ip} | {manufacturer} (แบรนด์คีย์: {brand_key})")
        if not user or not password:
            print("  ⚠️ ข้ามการตรวจสอบ: ยังไม่ได้กำหนดรหัสผ่าน (Credentials) ในแถบตั้งค่า")
            continue

        handler = get_handler(brand_key)
        
        # Loop channels 1 to 8
        for channel_id in range(1, 9):
            # Build channel-specific RTSP URL
            rtsp_url = handler.build_rtsp_url(ip, user, password, channel=channel_id, subtype=0, port=rtsp_port)
            
            print(f"  🔄 ช่องที่ {channel_id} ... ", end="", flush=True)
            traffic = check_rtsp_signal(ip, rtsp_port, rtsp_url, user, password)
            
            if isinstance(traffic, int):
                if traffic > 10000:
                    print(f"🟢 ONLINE     (Data: {traffic:,} Bytes)")
                else:
                    print(f"🔴 VIDEO LOSS (Data: {traffic:,} Bytes)")
            else:
                print(f"⚠️ ERROR      ({traffic})")

    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()
