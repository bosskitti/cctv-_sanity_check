def build_rtsp_url(ip, user, password, channel=1, subtype=1, port=554):
    stream_id = int(channel) * 100 + int(subtype) + 1
    return f"rtsp://{user}:{password}@{ip}:{port}/Streaming/Channels/{stream_id}"


def describe(device):
    return "Hikvision handler"
