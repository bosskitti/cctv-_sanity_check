from dataclasses import dataclass, field


@dataclass
class CameraCredentials:
    rtsp_user: str = ""
    rtsp_password: str = ""
    onvif_user: str = ""
    onvif_password: str = ""

    @property
    def has_rtsp(self):
        return bool(self.rtsp_user and self.rtsp_password)

    @property
    def has_onvif(self):
        return bool(self.onvif_user and self.onvif_password)


@dataclass
class CameraDevice:
    ip: str
    mac: str = ""
    manufacturer: str = "Unknown"
    model: str = "Unknown"
    xaddr: str = ""
    onvif_found: bool = False
    rtsp_open: bool = False
    open_ports: list[int] = field(default_factory=list)
    rtsp_auth_status: str = "NOT_CHECKED"
    credentials: CameraCredentials = field(default_factory=CameraCredentials)
    rtsp_url: str = ""
    rtsp_url_manual: bool = False

    @property
    def brand_key(self):
        text = f"{self.manufacturer} {self.model}".lower()
        from .brands import BRANDS_DATA
        for brand in BRANDS_DATA:
            for key in brand.get("keys", []):
                if key.lower() in text:
                    return brand.get("name", "").lower().replace(" ", "_").replace("-", "_")
        return "generic"
