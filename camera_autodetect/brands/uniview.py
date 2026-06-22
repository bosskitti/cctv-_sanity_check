def build_rtsp_url(ip, user, password, channel=1, subtype=0, port=554):
    stream = "0" if int(subtype) == 0 else "1"
    return f"rtsp://{user}:{password}@{ip}:{port}/media/video{channel}/{stream}"


def describe(device):
    return "Uniview handler"
