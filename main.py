"""Native desktop entry point with an authenticated loopback development server."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import threading
import traceback
import webbrowser

from telemetry.bridge import Bridge

ROOT = Path(__file__).resolve().parent / 'web'


def make_server(bridge, port=0):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            route = self.path.split('?')[0]
            if route not in files:
                self.send_error(404)
                return
            filename, mime = files[route]
            content = (ROOT / filename).read_bytes().replace(b'__API_TOKEN__', token.encode())
            self.send_response(200)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self):
            if self.path != '/api' or self.headers.get('X-Api-Token') != token:
                self.send_error(403)
                return
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 1048576:
                    raise ValueError('Invalid request size.')
                request = json.loads(self.rfile.read(size))
                response = bridge.call(request['action'], request.get('data'))
                body = json.dumps(response).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, KeyError, TypeError):
                self.send_error(400)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description='Axon')
    parser.add_argument('--browser', action='store_true', help='Open the dashboard in your browser')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    bridge = Bridge()
    server = make_server(bridge, args.port)
    url = f'http://127.0.0.1:{server.server_port}'
    if args.browser:
        print(f'Axon: {url}', flush=True)
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            bridge.close()
    else:
        try:
            import webview
        except ImportError:
            raise SystemExit('Install requirements.txt for desktop mode, or run python main.py --browser.')
        threading.Thread(target=server.serve_forever, daemon=True).start()
        size = bridge.app_state['window_size']
        bridge.window = webview.create_window('Axon', url, width=max(1050, size['width']), height=max(720, size['height']), min_size=(1050, 720))
        bridge.window.events.resized += bridge.remember_window_size
        def on_closing():
            if not bridge.prepare_close():
                return False
        bridge.window.events.closing += on_closing
        def attach_drop_handler():
            def on_drop(event):
                files = event.get('dataTransfer', {}).get('files', [])
                if files and files[0].get('pywebviewFullPath'):
                    result = bridge.call('load', {'path': files[0]['pywebviewFullPath']})
                    if 'request_error' in result:
                        with bridge.lock:
                            bridge.error = result['request_error']
            bridge.window.dom.get_element('#dropzone').events.drop += on_drop
        bridge.window.events.loaded += attach_drop_handler
        try:
            webview.start()
        finally:
            server.shutdown()
            server.server_close()
            bridge.close()


if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        # A windowed EXE has no console; keep startup failures inspectable.
        log_path = Path.home() / '.axf_telemetry' / 'startup.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('w', encoding='utf-8', buffering=1) as log:
            sys.stdout = sys.stderr = log
            try:
                main()
            except Exception:
                traceback.print_exc()
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, f'启动失败，请查看日志：\n{log_path}', 'Axon', 0x10)
    else:
        main()
