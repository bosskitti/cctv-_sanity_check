def build_rtsp_url(ip, user, password, channel=1, subtype=0, port=554):
    return f"rtsp://{user}:{password}@{ip}:{port}/cam/realmonitor?channel={channel}&subtype={subtype}"


def describe(device):
    return "Dahua/Imou handler"
