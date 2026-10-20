import sys
import shutil
from pathlib import Path

daemon_path = Path('/opt/shotcrypto/scanner_daemon.py')
text = daemon_path.read_text(encoding='utf-8')

old_block = """        class TLSHTTPServer(ThreadingHTTPServer):
            def get_request(self):
                # Handshake in the request thread, not the shared accept loop.
                # One client that connects without sending TLS must not block all devices.
                sock, address = self.socket.accept()
                sock.settimeout(5)
                try:
                    return tls.wrap_socket(sock,server_side=True,do_handshake_on_connect=False), address
                except Exception:
                    sock.close()
                    raise"""

new_block = """        class TLSHTTPServer(ThreadingHTTPServer):
            def get_request(self):
                # Handshake in the request thread, not the shared accept loop.
                # One client that connects without sending TLS must not block all devices.
                sock, address = self.socket.accept()
                sock.settimeout(5)
                try:
                    return tls.wrap_socket(sock,server_side=True,do_handshake_on_connect=False), address
                except Exception:
                    sock.close()
                    raise

            def handle_error(self, request, client_address):
                exc_type, exc_val, _ = sys.exc_info()
                if exc_type and issubclass(exc_type, (ssl.SSLError, ConnectionResetError, BrokenPipeError, TimeoutError, OSError)):
                    logger.debug("TLS/Network error from %s: %s", client_address, exc_val)
                    return
                super().handle_error(request, client_address)"""

if old_block in text:
    shutil.copy2(daemon_path, Path('/opt/shotcrypto/scanner_daemon.py.pre_tls_fix'))
    text = text.replace(old_block, new_block, 1)
    daemon_path.write_text(text, encoding='utf-8')
    print("SUCCESS: Patched TLSHTTPServer to handle SSL/network errors gracefully.")
else:
    print("WARNING: Old block not found in scanner_daemon.py!")
