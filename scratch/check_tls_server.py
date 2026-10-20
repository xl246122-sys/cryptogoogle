with open('/opt/shotcrypto/scanner_daemon.py', 'r', encoding='utf-8') as f:
    text = f.read()

start = text.find('class TLSHTTPServer')
if start != -1:
    print(text[start-100:start+600])
