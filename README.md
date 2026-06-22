# Camera Autodetect

ระบบนี้แยกเป็น 2 ชั้น:

1. `scanner` ค้นหาอุปกรณ์ในวง LAN ด้วย `arp-scan` ก่อน แล้ว map MAC กับ `latest_oui_lookup.json`
2. `brands` เลือกสคริปต์ตามแบรนด์ที่ detect ได้ แล้วสร้าง RTSP URL หรือ logic เฉพาะแบรนด์

ถ้าระบุ `--subnet` ระบบจะใช้ `arp-scan` หา IP/MAC ในวงก่อน จากนั้นเทียบ OUI แล้วเก็บเฉพาะ vendor ที่เข้าข่ายกล้องและ vendor ที่ยังเป็น `Unknown` ไว้เป็น candidate หลังจากนั้นจะใช้ `nmap -p- --open` scan port ทั้งหมดของ IP เหล่านั้นพร้อมกันหลายเครื่อง แล้วค่อย probe RTSP/ONVIF ต่อ

ถ้าไม่มี `arp-scan` หรือรันไม่ได้ ระบบจะ fallback ไปใช้ RTSP scan เดิมเมื่อมี `--subnet` ถ้าไม่มี `nmap` ระบบยัง detect จาก arp/OUI และ probe RTSP/ONVIF แบบเดิมได้ แต่จะไม่มีรายการ open ports ทั้งหมด

> ใช้เฉพาะกับกล้อง/ระบบเครือข่ายที่คุณมีสิทธิ์ดูแลเท่านั้น

## Requirements

ติดตั้งเครื่องมือ scan:

```bash
sudo apt install arp-scan nmap
```

บางระบบต้องรันด้วย `sudo` เพื่อให้ `arp-scan` ใช้งาน raw socket ได้:

```bash
sudo python3 -m camera_autodetect.main --scan --subnet 192.168.1.0/24
```

## Run

```bash
python3 -m camera_autodetect.main --scan
```

ระบุ subnet เพื่อช่วยหาอุปกรณ์ที่ไม่เปิด ONVIF:

```bash
python3 -m camera_autodetect.main --scan --subnet 192.168.1.0/24
```

สร้าง RTSP URL หลัง detect แบรนด์:

```bash
python3 main.py --scan --subnet 192.168.1.0/24 --credentials global --user admin --ask-password
```

ถ้า DVR/XVR/NVR แต่ละตัวใช้ user/password ไม่เหมือนกัน ให้ใช้โหมดกรอกแยกต่อเครื่องหลัง detect:

```bash
python3 main.py --scan --subnet 192.168.1.0/24 --credentials per-device
```

ตรวจว่า credential ใช้ดึง RTSP ได้จริงหรือไม่:

```bash
python3 main.py --scan --subnet 192.168.1.0/24 --credentials per-device --verify-rtsp
```

แยก credential ระหว่าง RTSP กับ ONVIF ได้:

```bash
python3 main.py --scan --credentials global --rtsp-user admin --ask-password --onvif-user onvif_admin
```

## เพิ่มแบรนด์ใหม่

เพิ่มไฟล์ใน `camera_autodetect/brands/` แล้ว register ที่ `brands/__init__.py`

## Web UI

รันด้วย Python:

```bash
python3 web.py --host 127.0.0.1 --port 8000
```

เปิดหน้าเว็บ:

```text
http://127.0.0.1:8000
```

รันด้วย Docker:

```bash
docker build -t camera-autodetect .
docker run --rm --network host camera-autodetect
```

แนะนำ `--network host` เพราะ ONVIF WS-Discovery ใช้ multicast ในวง LAN และการสแกน RTSP ต้องเห็น network เดียวกับกล้อง
