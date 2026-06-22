import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SOURCE_JSON_PATH = BASE_DIR / "source.json"

BRANDS_DATA = []
try:
    with open(SOURCE_JSON_PATH, "r", encoding="utf-8") as f:
        BRANDS_DATA = json.load(f).get("brands", [])
except Exception as e:
    print(f"Error loading source.json from {SOURCE_JSON_PATH}: {e}")


class DynamicBrandHandler:
    def __init__(self, brand_info):
        self.brand_info = brand_info
        self.name = brand_info.get("name", "Generic")
        self.rtsp_url_template = brand_info.get("rtsp_url_template", "rtsp://{user}:{password}@{ip}:{port}/")
        self.default_port = brand_info.get("rtsp_port", 554)
        self.stream_main = brand_info.get("stream_main", "")
        self.stream_sub = brand_info.get("stream_sub", "")

    def describe(self, device):
        return f"{self.name} handler"

    def build_rtsp_url(self, ip, user, password, channel=1, subtype=0, port=None):
        if port is None:
            port = self.default_port

        channel_index = int(channel) - 1
        channel_zero_index = int(channel) - 1
        stream = self.stream_main if int(subtype) == 0 else self.stream_sub

        url = self.rtsp_url_template
        # Clean user:password@ or credentials from URL if no user is specified
        if not user:
            url = url.replace("{user}:{password}@", "")
            url = url.replace("user={user}&password={password}&", "")
            url = url.replace("user={user}&password={password}", "")
            url = url.replace("{user}@", "")

        try:
            return url.format(
                user=user or "",
                password=password or "",
                ip=ip,
                port=port,
                channel=channel,
                channel_index=channel_index,
                channel_zero_index=channel_zero_index,
                stream=stream,
                subtype=subtype
            )
        except Exception:
            auth_part = f"{user}:{password}@" if user else ""
            return f"rtsp://{auth_part}{ip}:{port}/"


# Fallback generic handler
GENERIC_HANDLER = DynamicBrandHandler({
    "name": "Generic",
    "rtsp_port": 554,
    "rtsp_url_template": "rtsp://{user}:{password}@{ip}:{port}/",
    "stream_main": "",
    "stream_sub": ""
})

HANDLERS = {}
for brand in BRANDS_DATA:
    brand_key = brand.get("name", "").lower().replace(" ", "_").replace("-", "_")
    HANDLERS[brand_key] = DynamicBrandHandler(brand)


def get_handler(brand_key):
    if not brand_key:
        return GENERIC_HANDLER
    key = brand_key.lower().replace(" ", "_").replace("-", "_")
    return HANDLERS.get(key, GENERIC_HANDLER)

