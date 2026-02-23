import socket
import json
import threading
import time
import os
from colorama import init, Fore, Style
import signal

init(autoreset=True)

# Globals
client_socket = Noneclient_address = None
running = True

def print_header():
    print(Fore.CYAN + "=" * 80)
    print(Fore.CYAN + "      REMOTE C2 AGENT - PURE TCP PROXY ARCHITECTURE")
    print(Fore.CYAN + "=" * 80)

def handle_incoming_data(data):
    """Mencetak data mentah dari perangkat ke log server."""
    try:
        # Anda bisa menambahkan logika parsing JSON di sini jika perlu
        print(f"\n{Fore.GREEN}[RECV]: {data[:400]}")
    except Exception as e:
        print(f"\n{Fore.RED}[ERROR] Could not process data: {e}")

def handle_connection(conn, addr):
    global client_socket, client_address
    buffer = ""
    try:
        client_socket, client_address = conn, addr
        print(f"\n{Fore.GREEN}[+] TCP Connection Accepted from {addr[0]}:{addr[1]}")

        while running:
            data = conn.recv(16384).decode('utf-8', errors='ignore')
            if not data:
                break
            buffer += data
            # Proses data baris per baris
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                if line.strip():
                    handle_incoming_data(line.strip())
    except (ConnectionResetError, BrokenPipeError, socket.timeout):
        print(f"\n{Fore.YELLOW}[INFO] Client connection lost.")
    finally:
        print(f"\n{Fore.RED}[-] TCP Client Disconnected.")
        client_socket = None
        client_address = None
        conn.close()

def start_server(host, port):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((host, port))
    except Exception as e:
        print(f"{Fore.RED}[FATAL] Could not bind to port {port}: {e}")
        os._exit(1)

    server_socket.listen(1)
    print(f"[*] Pure TCP server listening internally on {host}:{port}")

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
            if running:
                print(f"{Fore.RED}[ERROR] Server exception: {e}")
            break
    server_socket.close()

if __name__ == '__main__':
    print_header()
    # Port internal yang akan diekspos oleh TCP Proxy Railway
    INTERNAL_PORT = 9090
    
    server_thread = threading.Thread(target=start_server, args=('0.0.0.0', INTERNAL_PORT), daemon=True)
    server_thread.start()

    # Loop utama untuk menjaga agar skrip tetap berjalan
    print("[INFO] Server is running. Press Ctrl+C to exit.")
    while running:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            print("\n[INFO] Shutdown signal received.")
            running = False

    print("[INFO] Server shutting down.")
