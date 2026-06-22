import socket
import time
import re
import hashlib

def check_coaxial_signal(ip, port, channel, user, password):
    """
    ฟังก์ชันแกนหลัก: สั่ง PLAY สตรีมจริงผ่าน TCP แล้วจับมวลน้ำข้อมูลใน 1 วินาที
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.5)
    
    try:
        s.connect((ip, port))
    except:
        return "ERROR_CONN"

    url = f"rtsp://{ip}:{port}/cam/realmonitor?channel={channel}&subtype=0"
    
    # Step 1: Handshake
    req1 = f"DESCRIBE {url} RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: Lavf58.29.100\r\nAccept: application/sdp\r\n\r\n"
    s.send(req1.encode())
    try:
        res1 = s.recv(1024).decode('utf-8', errors='ignore')
    except:
        s.close()
        return "TIMEOUT"
        
    if "401 Unauthorized" not in res1:
        s.close()
        return "AUTH_ERROR"
        
    # Step 2: Digest Authentication
    realm_match = re.search(r'realm="([^"]+)"', res1)
    nonce_match = re.search(r'nonce="([^"]+)"', res1)
    if not realm_match or not nonce_match:
        s.close()
        return "AUTH_HEADER_ERROR"

    realm = realm_match.group(1)
    nonce = nonce_match.group(1)
    ha1 = hashlib.md5(f"{user}:{realm}:{password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"DESCRIBE:{url}".encode()).hexdigest()
    response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
    auth_header = f'Digest username="{user}", realm="{realm}", nonce="{nonce}", uri="{url}", response="{response}"'
    
    req2 = f"DESCRIBE {url} RTSP/1.0\r\nCSeq: 2\r\nUser-Agent: Lavf58.29.100\r\nAuthorization: {auth_header}\r\nAccept: application/sdp\r\n\r\n"
    s.send(req2.encode())
    try:
        s.recv(2048)
    except:
        s.close()
        return "TIMEOUT"

    # Step 3: SETUP TCP Stream
    req_setup = f"SETUP {url}/trackID=0 RTSP/1.0\r\nCSeq: 3\r\nUser-Agent: Lavf58.29.100\r\nAuthorization: {auth_header}\r\nTransport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n\r\n"
    s.send(req_setup.encode())
    try:
        res_setup = s.recv(1024).decode('utf-8', errors='ignore')
    except:
        s.close()
        return "TIMEOUT"
    
    session_match = re.search(r'Session:\s*([;\w]+)', res_setup)
    if not session_match:
        s.close()
        return "SETUP_FAILED"
    session_id = session_match.group(1).split(';')[0]

    # Step 4: PLAY Stream
    req_play = f"PLAY {url} RTSP/1.0\r\nCSeq: 4\r\nUser-Agent: Lavf58.29.100\r\nAuthorization: {auth_header}\r\nSession: {session_id}\r\n\r\n"
    s.send(req_play.encode())
    try:
        s.recv(1024)
    except:
        s.close()
        return "TIMEOUT"
    
    # Step 5: ตะปบวัดขนาดข้อมูลจริงที่ไหลผ่าน Socket ในเวลา 1 วินาที
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

# ========================================================
# ส่วนแสดงผลลัพธ์การสแกนสดทุกช่องสัญญาณ (Main Loop)
# ========================================================
if __name__ == "__main__":
    dvr_ip = "192.168.1.108"
    rtsp_port = 554
    
    print("\n" + "="*60)
    print(" 📡 รายงานสัญญาณสาย Coaxial เรียลไทม์ครบทุกช่อง (8 CHANNELS)")
    print("="*60)
    
    # วิ่งลูปตรวจสอบให้ครบทุกสายตามจริง (ช่อง 1 ถึง ช่อง 8)
    for channel_id in range(1, 9):
        print(f"🔄 กำลังเช็คสถานะสาย ช่องที่ {channel_id} ... ", end="", flush=True)
        
        # ยิงคำสั่งวัดมวลน้ำข้อมูลจริง
        traffic_weight = check_coaxial_signal(dvr_ip, rtsp_port, channel_id, "boss", "boss2546")
        
        # แสดงผลลัพธ์คัดกรองตามตรรกะความหนาแน่นข้อมูล
        if isinstance(traffic_weight, int):
            if traffic_weight > 25000:
                print(f"🟢 ONLINE     (Data: {traffic_weight:,} Bytes)")
            else:
                print(f"🔴 VIDEO LOSS (Data: {traffic_weight:,} Bytes)")
        else:
            print(f"⚠️ ERROR      ({traffic_weight})")
            
    print("="*60 + "\n")
