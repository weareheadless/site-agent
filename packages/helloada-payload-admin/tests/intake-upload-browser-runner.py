import http.server, json, os, socketserver, sys, threading, time
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(sys.argv[1]); os.chdir(root)
uploads=[]; errors=[]
class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/preview'):
            body=b'<!doctype html><main><h1 data-helloada-field="field-0">Fixture preview</h1></main>'
            self.send_response(200); self.send_header('Content-Type','text/html'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        if self.path.startswith('/api/helloada/media-library'):
            media=[{'id':11,'filename':'existing.png','alt':'Existing gallery image','url':'/fixture-existing.png','tags':['existing-tag'],'analysisStatus':'ready'}]
            if uploads: media.insert(0,{'id':731,'filename':'owner-upload.png','alt':'Uploaded fixture','url':'/fixture-upload.png','tags':['fixture-tag'],'analysisStatus':'ready'})
            payload=json.dumps({'media':media,'hasNextPage':False}).encode()
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload); return
        if self.path=='/fixture-existing.png':
            self.send_response(200); self.send_header('Content-Type','image/png'); self.end_headers(); self.wfile.write(b'\x89PNG\r\n\x1a\n'); return
        if self.path=='/fixture-upload.png':
            self.send_response(200); self.send_header('Content-Type','image/png'); self.end_headers(); self.wfile.write(b'\x89PNG\r\n\x1a\n'); return
        if self.path=='/favicon.ico': self.send_response(204); self.end_headers(); return
        super().do_GET()
    def do_POST(self):
        if self.path!='/api/helloada/media/upload': self.send_error(404); return
        length=int(self.headers.get('Content-Length','0'))
        chunks=[]; remaining=length
        # Deliberately consume at a bounded rate so the browser emits observable
        # native XHR upload progress events, without faking the request/event.
        while remaining:
            block=self.rfile.read(min(128*1024,remaining))
            if not block: break
            chunks.append(block); remaining-=len(block); time.sleep(.015)
        raw=b''.join(chunks)
        assert b'name="file"' in raw and b'owner-upload.png' in raw, 'multipart file field/name missing'
        uploads.append({'bytes':len(raw),'content_type':self.headers.get('Content-Type','')})
        self.send_response(201); self.send_header('Content-Type','application/json'); self.send_header('Access-Control-Allow-Origin','*'); self.end_headers()
        self.wfile.write(json.dumps({'attachment':{'asset_id':731,'name':'owner-upload.png','url':'/fixture-upload.png','thumbnail_url':'/fixture-upload.png','alt_text':'Uploaded fixture','tags':['fixture-tag'],'analysis_status':'ready'}}).encode())
    def log_message(self,*_): pass
server=socketserver.TCPServer(('127.0.0.1',0),Handler); threading.Thread(target=server.serve_forever,daemon=True).start()
base=f'http://127.0.0.1:{server.server_address[1]}'
browser_path='/home/admin/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'
report=[]
try:
  with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,executable_path=browser_path,args=['--no-sandbox'])
    page=browser.new_page(); page.on('pageerror',lambda e:errors.append(f'PAGEERROR {e}'))
    page.on('console',lambda m:errors.append(f'CONSOLE {m.text}') if m.type=='error' else None)
    page.on('response',lambda r:errors.append(f'HTTP {r.status} {r.url}') if r.status>=400 else None)
    page.on('requestfailed',lambda r:errors.append(f'REQUESTFAILED {r.url}: {r.failure}'))
    page.set_default_timeout(8000)
    for width,height in [(1440,900),(390,844)]:
      page.set_viewport_size({'width':width,'height':height}); page.goto(base+'/index.html')
      page.locator('.helloada-chat-form').wait_for()
      page.locator('.helloada-attach-button').evaluate('(el)=>el.click()')
      gallery=page.locator('.helloada-chat-gallery[role=dialog]'); gallery.wait_for()
      gallery.get_by_text('Existing gallery image').wait_for()
      assert gallery.get_by_text('existing-tag').is_visible(), 'existing gallery tags absent'
      file_input=page.locator('.helloada-file-input')
      file_input.set_input_files({'name':'owner-upload.png','mimeType':'image/png','buffer':b'\x89PNG\r\n\x1a\n'+b'x'*(12*1024*1024)})
      thumb=gallery.locator('.helloada-chat-upload-preview img[alt=""]')
      thumb.wait_for(); assert thumb.is_visible(), 'uploading thumbnail not visible inside gallery'
      progress=gallery.locator('progress[aria-label="owner-upload.png upload progress"]')
      progress.wait_for(); page.wait_for_function("() => { const p=document.querySelector('.helloada-chat-gallery progress[aria-label=\\\"owner-upload.png upload progress\\\"]'); return p && Number(p.value)>0 }",timeout=15000)
      start=progress.get_attribute('value')
      assert start is not None and float(start) >= 0, ('progress value unavailable',width,start)
      pending=page.locator('.helloada-pending-attachment').filter(has_text='owner-upload.png')
      pending.get_by_text('Ready').wait_for(timeout=15000)
      assert gallery.locator('.helloada-chat-upload-preview').count()==0, 'uploading preview did not clear after success'
      assert gallery.get_by_text('Uploaded fixture').is_visible(), 'uploaded file missing from gallery'
      assert gallery.get_by_text('fixture-tag').is_visible(), 'uploaded file tags missing from gallery'
      assert page.locator('.helloada-send-button').is_enabled(), 'ready attachment was not retained in chat composer'
      assert len(uploads)==(1 if width==1440 else 2), 'expected actual local HTTP POST per viewport'
      overflow=page.evaluate('({width:document.documentElement.scrollWidth,client:document.documentElement.clientWidth})')
      assert overflow['width']<=overflow['client'], ('horizontal overflow',width,overflow)
      page.screenshot(path=f'{root}/upload-{width}.png',full_page=True)
      report.append(f'{width}x{height}: local multipart POST; native progress observed (initial value {start}); gallery thumbnail, success, tags and retained attachment verified; no horizontal overflow')
    if errors: raise AssertionError('\n'.join(errors))
    (root/'browser-report.txt').write_text('\n'.join(report)+'\nNo console, page, HTTP, or request failures.\n')
    browser.close()
finally: server.shutdown()
