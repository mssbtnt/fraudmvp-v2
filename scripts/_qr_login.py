#!/usr/bin/env python3
"""QR login with HTTP server — serves QR image directly for fast access."""
import asyncio, os, threading
from dotenv import load_dotenv
load_dotenv()
from telethon import TelegramClient
import qrcode
import http.server
import socketserver

SESSION = 'group_session'
PORT = 8888

# ─── Tiny HTTP server for QR PNG ───────────────────────────────────────────────

class QRHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/qr.png':
            self.send_response(200)
            self.send_header('Content-type', 'image/png')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            with open('/tmp/telegram_qr.png', 'rb') as f:
                self.wfile.write(f.read())
        elif self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'''<!DOCTYPE html>
<html><head><title>Telegram QR</title>
<meta http-equiv="refresh" content="5">
<style>body{font-family:sans-serif;text-align:center;padding:40px;background:#1a1a2e;color:#eee}
img{max-width:300px;border:4px solid #00d7ff;border-radius:12px}
p{color:#888;margin-top:20px}
</style></head><body>
<h2>Telegram QR Login</h2>
<img src="/qr.png?cb=1" alt="QR Code" />
<p>Scan with Telegram (Settings &gt; Devices &gt; Link a Device)</p>
<p>If image does not update, tap/click it to reload</p>
</body></html>''')
        else:
            self.send_response(404)
    def log_message(self, fmt, *args): pass  # silent

def start_server():
    with socketserver.TCPServer(("", PORT), QRHandler) as httpd:
        httpd.handle_request()

# ─── Main ─────────────────────────────────────────────────────────────────────

async def main():
    client = TelegramClient(
        SESSION,
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'),
    )
    await client.connect()

    print('Initiating QR login...', flush=True)
    qr_login = await client.qr_login()

    img = qrcode.make(qr_login.url)
    img.save('/tmp/telegram_qr.png')

    # Start HTTP server in background thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    ip = os.popen("hostname -I | awk '{print $1}'").read().strip()
    print(f'QR at: http://{ip}:{PORT}/qr.png', flush=True)
    print(f'QR at: http://localhost:{PORT}/qr.png', flush=True)

    # Wait for scan
    print('Waiting for QR scan... (120s)', flush=True)
    await qr_login.wait(timeout=120)
    print('AUTH_OK', flush=True)

    me = await client.get_me()
    print(f'Logged in as: {me.first_name}', flush=True)

    count = 0
    async for d in client.iter_dialogs():
        if hasattr(d.entity, 'title') and d.entity.username:
            print(f'  @{d.entity.username}  —  {d.entity.title}', flush=True)
            count += 1
    print(f'TOTAL:{count}', flush=True)

    await client.disconnect()

asyncio.run(main())
