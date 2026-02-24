import asyncio
import json
import os
import logging
import websockets
from http import HTTPStatus

# --- Configuration & Globals ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Port for the Android agent TCP connection. Using a high, non-standard port.
TCP_PORT = 9999
# Port for the Web UI (HTTP/WebSocket). We hardcode this to avoid conflict with Railways' $PORT variable.
WEB_PORT = 8080

# This will hold the connection to the Android agent
AGENT_WRITER = None
# A set of all connected Web UI clients
WEB_CLIENTS = set()

# --- Core Bridge Logic ---

async def broadcast_to_web(message):
    """Sends a message to all connected Web UI clients."""
    if WEB_CLIENTS:
        await websockets.broadcast(WEB_CLIENTS, message)

async def forward_to_agent(command):
    """Forwards a command from the Web UI to the Android agent."""
    global AGENT_WRITER
    if AGENT_WRITER:
        try:
            AGENT_WRITER.write((command + '\n').encode())
            await AGENT_WRITER.drain()
            logging.info(f"Forwarded to agent: {command[:50]}...")
            return True
        except (ConnectionResetError, BrokenPipeError):
            logging.warning("Agent connection lost while trying to send.")
            await handle_agent_disconnection()
            return False
    else:
        logging.warning("Command received but no agent is connected.")
        return False

async def handle_agent_disconnection():
    """Cleans up after the agent disconnects."""
    global AGENT_WRITER
    if AGENT_WRITER:
        AGENT_WRITER = None
        logging.info("Agent disconnected.")
        await broadcast_to_web(json.dumps({'type': 'status', 'payload': 'agent_disconnected'}))

# --- Server Handlers ---

async def http_and_ws_handler(websocket, path):
    """Handles incoming WebSocket connections from the Web UI."""
    global WEB_CLIENTS
    WEB_CLIENTS.add(websocket)
    logging.info(f"Web client connected: {websocket.remote_address}")
    if AGENT_WRITER:
        await websocket.send(json.dumps({'type': 'status', 'payload': 'agent_connected'}))
    else:
        await websocket.send(json.dumps({'type': 'status', 'payload': 'agent_disconnected'}))

    try:
        async for message in websocket:
            logging.info(f"Received from web: {message[:100]}")
            success = await forward_to_agent(message)
            if not success:
                await websocket.send(json.dumps({'type': 'error', 'payload': 'Command failed: Agent not connected.'}))
    except websockets.exceptions.ConnectionClosed:
        logging.info(f"Web client disconnected: {websocket.remote_address}")
    finally:
        WEB_CLIENTS.remove(websocket)

# Get the absolute path of the directory where the script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML_PATH = os.path.join(SCRIPT_DIR, 'index.html')

async def serve_http(path, request_headers):
    """Serves the index.html file for GET requests using an absolute path."""
    if path == "/":
        if not os.path.exists(INDEX_HTML_PATH):
            msg = f"500 Internal Server Error: index.html not found at expected path: {INDEX_HTML_PATH}"
            logging.critical(msg)
            return HTTPStatus.INTERNAL_SERVER_ERROR, [], msg.encode()
        try:
            with open(INDEX_HTML_PATH, 'r') as f:
                html_content = f.read()
            return HTTPStatus.OK, [('Content-Type', 'text/html')], html_content.encode()
        except Exception as e:
            msg = f"500 Internal Server Error: Failed to read index.html. Reason: {e}"
            logging.error(msg)
            return HTTPStatus.INTERNAL_SERVER_ERROR, [], msg.encode()
    return None

async def tcp_agent_handler(reader, writer):
    """Handles the TCP connection from the Android agent."""
    global AGENT_WRITER
    if AGENT_WRITER:
        logging.warning("New agent tried to connect, but one is already active. Closing new connection.")
        writer.close()
        await writer.wait_closed()
        return

    AGENT_WRITER = writer
    addr = writer.get_extra_info('peername')
    logging.info(f"Android agent connected from {addr}")
    await broadcast_to_web(json.dumps({'type': 'status', 'payload': 'agent_connected'}))

    buffer = ""
    try:
        while True:
            data = await reader.read(16384)
            if not data: break
            buffer += data.decode('utf-8', errors='ignore')
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                if line.strip():
                    logging.info(f"Received from agent: {line.strip()}")
                    await broadcast_to_web(line.strip())
    except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
        logging.info("Agent connection closed.")
    finally:
        writer.close()
        await writer.wait_closed()
        await handle_agent_disconnection()

# --- Main Execution ---

async def main():
    """Starts both the TCP and Web servers."""
    logging.info(f"Starting servers. WEB on port {WEB_PORT}, TCP on port {TCP_PORT}.")
    tcp_server = await asyncio.start_server(tcp_agent_handler, '0.0.0.0', TCP_PORT)
    web_server = await websockets.serve(http_and_ws_handler, '0.0.0.0', WEB_PORT, process_request=serve_http)
    await asyncio.gather(tcp_server.serve_forever(), web_server.serve_forever())

if __name__ == '__main__':
    if str(WEB_PORT) == str(TCP_PORT):
        logging.critical(f"FATAL: Web Port ({WEB_PORT}) and TCP Port ({TCP_PORT}) must be different!")
        exit(1)
    try:
        asyncio.run(main())
    except Exception as e:
        logging.critical(f"Failed to start servers: {e}")
