
import asyncio
import json
import os
import logging
import websockets
from http import HTTPStatus

# --- Configuration & Globals ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Port for the Android agent TCP connection. MUST BE DIFFERENT FROM WEB_PORT.
TCP_PORT = 9090
# Port for the Web UI (HTTP/WebSocket), provided by Railways environment variable 'PORT'
WEB_PORT = int(os.environ.get('PORT', 8080))

# This will hold the connection to the Android agent
AGENT_WRITER = None
# A set of all connected Web UI clients
WEB_CLIENTS = set()

# --- Core Bridge Logic ---

async def broadcast_to_web(message):
    """Sends a message to all connected Web UI clients."""
    if WEB_CLIENTS:
        # websockets.broadcast is efficient for sending to multiple clients
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
    await broadcast_to_web(json.dumps({'type': 'status', 'payload': 'web_client_connected'}))
    # Inform the new client about the current agent status
    if AGENT_WRITER:
        await websocket.send(json.dumps({'type': 'status', 'payload': 'agent_connected'}))
    else:
        await websocket.send(json.dumps({'type': 'status', 'payload': 'agent_disconnected'}))

    try:
        # Listen for commands from this web client
        async for message in websocket:
            logging.info(f"Received from web: {message[:100]}")
            success = await forward_to_agent(message)
            if not success:
                await websocket.send(json.dumps({'type': 'error', 'payload': 'Command failed: Agent not connected.'}))
    except websockets.exceptions.ConnectionClosed:
        logging.info(f"Web client disconnected: {websocket.remote_address}")
    finally:
        WEB_CLIENTS.remove(websocket)

async def serve_http(path, request_headers):
    """Serves the index.html file for GET requests."""
    if path == "/":
        try:
            with open('index.html', 'r') as f:
                html_content = f.read()
            return HTTPStatus.OK, [('Content-Type', 'text/html')], html_content.encode()
        except FileNotFoundError:
            logging.error("index.html not found!")
            return HTTPStatus.NOT_FOUND, [], b"404 Not Found"
    # Let the WebSocket handler take over for non-root paths
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
            if not data:
                break # Connection closed by agent

            buffer += data.decode('utf-8', errors='ignore')
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                if line.strip():
                    logging.info(f"Received from agent: {line.strip()}")
                    # Forward agent data to all web clients
                    await broadcast_to_web(line.strip())

    except asyncio.CancelledError:
        logging.info("Agent handler cancelled.")
    except (ConnectionResetError, BrokenPipeError):
        logging.info("Agent connection reset by peer.")
    finally:
        writer.close()
        await writer.wait_closed()
        await handle_agent_disconnection()

# --- Main Execution ---

async def main():
    """Starts both the TCP and Web servers."""
    # Start the TCP server for the Android agent
    tcp_server = await asyncio.start_server(tcp_agent_handler, '0.0.0.0', TCP_PORT)
    logging.info(f"TCP server listening on port {TCP_PORT}")

    # Start the Web server for the UI (HTTP/WebSocket)
    web_server = await websockets.serve(
        http_and_ws_handler,
        '0.0.0.0',
        WEB_PORT,
        process_request=serve_http
    )
    logging.info(f"Web server (HTTP/WebSocket) listening on port {WEB_PORT}")

    # Run both servers concurrently
    await asyncio.gather(tcp_server.serve_forever(), web_server.serve_forever())

if __name__ == '__main__':
    if WEB_PORT == TCP_PORT:
        logging.critical(f"CRITICAL ERROR: Web Port and TCP Port cannot be the same! (Port: {WEB_PORT})")
        exit(1)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Servers shutting down.")
    except OSError as e:
        logging.critical(f"OSError on startup: {e}. Check if ports are available.")
