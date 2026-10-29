import http.server, os, socketserver, sys, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(sys.argv[1]); os.chdir(root)
errors = []
def check_footer(buttons, height, surface, width):
    assert buttons.count() > 0, (surface, 'missing action buttons')
    for button in buttons.all():
        box = button.bounding_box()
        assert box and box['y'] >= 0 and box['y'] + box['height'] <= height, (surface, width, height, box)
        hit = button.evaluate('(el)=>{const b=el.getBoundingClientRect();const top=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);return top===el||el.contains(top)}')
        assert hit, (surface, 'occluded', button.inner_text())

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/favicon.ico': self.send_response(204); self.end_headers(); return
        super().do_GET()
    def log_message(self, *_): pass
server = socketserver.TCPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f'http://127.0.0.1:{server.server_address[1]}'
browser_path = '/home/admin/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome'
try:
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=browser_path, args=['--no-sandbox'])
    page = browser.new_page(); page.on('pageerror', lambda e: errors.append(f'PAGEERROR {e}'))
    page.on('console', lambda m: errors.append(f'CONSOLE {m.text}') if m.type == 'error' else None)
    page.on('response', lambda r: errors.append(f'HTTP {r.status} {r.url}') if r.status >= 400 else None)
    page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body='<main><h1 data-helloada-field="field-0">Fixture heading</h1></main>') if '/preview' in route.request.url else route.continue_())
    page.goto(base + '/index.html')
    trigger = page.locator('.helloada-review-decision .helloada-draft-action'); trigger.wait_for(timeout=5000)
    outputs=[]
    for width,height in [(1440,900),(390,844),(390,480)]:
      page.set_viewport_size({'width':width,'height':height})
      dialog=page.locator('.helloada-publish-dialog')
      assert not dialog.is_visible() and dialog.evaluate('(el)=>document.elementFromPoint(innerWidth/2,innerHeight/2)!==el'), ('closed publish dialog occludes',width,height)
      page.set_viewport_size({'width':1440,'height':900})
      if width <= 560:
        page.locator('#helloada-website-tab').evaluate('(el)=>el.click()')
      trigger.evaluate('(el)=>el.click()')
      page.set_viewport_size({'width':width,'height':height})
      check_footer(dialog.locator('footer button'),height,'publish',width)
      outputs.append(f'publish open {width}x{height}: visible footer, hit-testable')
      page.screenshot(path=f'{root}/publish-{width}x{height}.png', full_page=True)
      dialog.locator('footer button').first.evaluate('(el)=>el.click()')
      assert not dialog.is_visible(), ('publish dialog remains visible after close',width,height)
    page.set_viewport_size({'width':1440,'height':900})
    page.locator('.helloada-preview-options summary').click()
    page.get_by_role('button',name='owner.editManually').evaluate('(el)=>el.click()')
    editor=page.locator('.helloada-page-editor'); editor.wait_for()
    for width,height in [(1440,900),(390,844),(390,480)]:
      page.set_viewport_size({'width':width,'height':height}); check_footer(editor.locator('.helloada-page-editor-footer button'),height,'page-editor',width)
      outputs.append(f'page editor {width}x{height}: visible footer, hit-testable')
      page.screenshot(path=f'{root}/page-editor-{width}x{height}.png',full_page=True)
    editor.locator('.helloada-page-editor-footer button').first.evaluate('(el)=>el.click()')
    page.set_viewport_size({'width':1440,'height':900})
    outputs.append('field editor: not browser-exercised; mocked preview quick-edit target was not reached')
    if errors: raise AssertionError('\n'.join(errors))
    (root/'browser-report.txt').write_text('\n'.join(outputs)+'\nNo console, page, or HTTP errors.\n')
    browser.close()
finally: server.shutdown()
