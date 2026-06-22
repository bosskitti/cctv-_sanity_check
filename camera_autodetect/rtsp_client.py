import base64
import hashlib
import os
import re
import socket
from urllib.parse import urlparse, urlunparse


def verify_rtsp_credentials(rtsp_url, user, password, timeout=3.0):
    request_url = strip_url_credentials(rtsp_url)
    first = send_describe(request_url, timeout=timeout)
    if first is None:
        return "TIMEOUT"

    if status_code(first) == 200:
        return "OK"
    if status_code(first) != 401:
        return f"RTSP_{status_code(first) or 'ERROR'}"

    challenge = parse_auth_challenge(first)
    if not challenge:
        return "AUTH_REQUIRED"

    auth_header = build_auth_header(challenge, user, password, "DESCRIBE", request_url)
    if not auth_header:
        return "AUTH_UNSUPPORTED"

    second = send_describe(request_url, auth_header=auth_header, cseq=2, timeout=timeout)
    if second is None:
        return "TIMEOUT"
    if status_code(second) == 200:
        return "OK"
    if status_code(second) == 401:
        return "AUTH_FAILED"
    return f"RTSP_{status_code(second) or 'ERROR'}"


def strip_url_credentials(rtsp_url):
    parsed = urlparse(rtsp_url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme, host, parsed.path, parsed.params, parsed.query, parsed.fragment))


def send_describe(rtsp_url, auth_header=None, cseq=1, timeout=3.0):
    parsed = urlparse(rtsp_url)
    port = parsed.port or 554
    host = parsed.hostname
    if not host:
        return None

    lines = [
        f"DESCRIBE {rtsp_url} RTSP/1.0",
        f"CSeq: {cseq}",
        "User-Agent: camera-autodetect",
        "Accept: application/sdp",
    ]
    if auth_header:
        lines.append(f"Authorization: {auth_header}")
    request = "\r\n".join(lines) + "\r\n\r\n"

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.sendall(request.encode("utf-8"))
        return sock.recv(4096).decode("utf-8", errors="ignore")
    except OSError:
        return None
    finally:
        sock.close()


def status_code(response):
    match = re.search(r"RTSP/\d\.\d\s+(\d+)", response)
    return int(match.group(1)) if match else None


def parse_auth_challenge(response):
    match = re.search(r"WWW-Authenticate:\s*(.+)", response, re.I)
    if not match:
        return None

    value = match.group(1).strip()
    scheme, _, params_text = value.partition(" ")
    params = dict(re.findall(r'(\w+)="?([^",]+)"?', params_text))
    return {"scheme": scheme.lower(), "params": params}


def build_auth_header(challenge, user, password, method, uri):
    scheme = challenge["scheme"]
    params = challenge["params"]

    if scheme == "basic":
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    if scheme != "digest":
        return None

    realm = params.get("realm", "")
    nonce = params.get("nonce", "")
    qop = params.get("qop", "")
    algorithm = params.get("algorithm", "MD5").upper()
    if algorithm != "MD5" or not realm or not nonce:
        return None

    ha1 = hashlib.md5(f"{user}:{realm}:{password}".encode("utf-8")).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode("utf-8")).hexdigest()

    auth_parts = [
        f'username="{user}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{uri}"',
    ]

    if "auth" in qop:
        nc = "00000001"
        cnonce = hashlib.md5(os.urandom(8)).hexdigest()[:16]
        response = hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}".encode("utf-8")).hexdigest()
        auth_parts.extend([f'response="{response}"', 'qop="auth"', f"nc={nc}", f'cnonce="{cnonce}"'])
    else:
        response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode("utf-8")).hexdigest()
        auth_parts.append(f'response="{response}"')

    return "Digest " + ", ".join(auth_parts)


def check_rtsp_signal(ip, port, rtsp_url, user, password):
    import time
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
