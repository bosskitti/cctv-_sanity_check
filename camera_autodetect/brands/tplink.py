def build_rtsp_url(ip, user, password, channel=1, subtype=0, port=554):
    stream = "stream1" if int(subtype) == 0 else "stream2"
    return f"rtsp://{user}:{password}@{ip}:{port}/{stream}"


def describe(device):
    return "TP-Link/Tapo/VIGI handler"
