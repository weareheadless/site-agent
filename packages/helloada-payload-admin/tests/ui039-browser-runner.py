import http.server, os, socketserver, sys, threading
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(sys.argv[1]); os.chdir(root)
errors = []
viewports = [(1440, 900), (390, 844), (390, 480)]

def check_footer(buttons, height, surface, width):
    assert buttons.count() > 0, (surface, 'missing action buttons')
    for button in buttons.all():
        box = button.bounding_box()
        assert box and box['y'] >= 0 and box['y'] + box['height'] <= height, (surface, width, height, box)
        hit = button.evaluate('(el)=>{const b=el.getBoundingClientRect();const top=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);return top===el||el.contains(top)}')
        assert hit, (surface, 'occluded', button.inner_text())

def check_overflow(region, surface, width, height, required):
    metrics = region.evaluate('(el)=>({scrollHeight:el.scrollHeight,clientHeight:el.clientHeight,overflow:getComputedStyle(el).overflowY})')
    assert metrics['overflow'] in ('auto', 'scroll'), (surface, 'body has no scroll behavior', metrics)
    if required:
        assert metrics['scrollHeight'] > metrics['clientHeight'], (surface, width, height, 'body does not overflow', metrics)

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
    page.set_default_timeout(5000)
    page.on('console', lambda m: errors.append(f'CONSOLE {m.text}') if m.type == 'error' else None)
    page.on('response', lambda r: errors.append(f'HTTP {r.status} {r.url}') if r.status >= 400 else None)
    page.on('requestfailed', lambda r: errors.append(f'REQUESTFAILED {r.url}: {r.failure}'))
    page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body='<main><h1 data-helloada-field="field-0">Fixture heading</h1><script>window.__pointerEventCount=0;window.__lastPointerTarget="";document.addEventListener("pointerover",e=>{window.__pointerEventCount++;window.__lastPointerTarget=e.target?.tagName||""},true)</script></main>') if '/preview' in route.request.url else route.continue_())
    page.goto(base + '/index.html')
    page.locator('.helloada-review-decision .helloada-draft-action').wait_for(timeout=5000)
    outputs=[]

    # The native publish dialog must be absent from layout/hit testing until opened.
    publish = page.locator('.helloada-publish-dialog')
    for width, height in viewports:
      page.set_viewport_size({'width': width, 'height': height})
      assert not publish.is_visible(), ('closed publish dialog is visible before open', width, height)
      assert publish.evaluate('(el)=>!el.open && (el.getBoundingClientRect().width===0 || document.elementFromPoint(innerWidth/2,innerHeight/2)!==el)'), ('closed publish dialog occludes before open', width, height)
      page.set_viewport_size({'width': 1440, 'height': 900})
      page.locator('.helloada-review-decision .helloada-draft-action').click()
      page.set_viewport_size({'width': width, 'height': height})
      check_footer(publish.locator('footer button'), height, 'publish', width)
      check_overflow(publish.locator('.helloada-publish-dialog-scroll'), 'publish', width, height, (width, height) == (390, 480))
      outputs.append(f'publish {width}x{height}: overflowing body; footer hit-testable')
      page.screenshot(path=f'{root}/publish-{width}x{height}.png', full_page=True)
      publish.get_by_role('button', name='Keep reviewing').click()
      assert not publish.is_visible(), ('publish dialog remains visible after close', width, height)

    # Open the actual quick-edit controls. The manually-edit button opens a
    # different, full-page editor and is deliberately not used for this path.
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.locator('.helloada-preview-options summary').click()
    checkbox = page.locator('.helloada-preview-options input[type=checkbox]')
    assert checkbox.count() == 1, ('quick-edit checkbox missing', page.locator('.helloada-preview-options').inner_text())
    checkbox.evaluate('(el)=>el.click()')  # Deliberately hidden native checkbox; its own handler is real.
    frame = page.frame_locator('iframe.helloada-preview-frame')
    target = frame.locator('[data-helloada-field="field-0"]')
    target.wait_for(timeout=5000)
    # Preserve the original obstruction as evidence, then dismiss the native
    # details menu exactly as a user can: an ordinary click on its summary.
    covered_target = target.evaluate('(el)=>{const r=el.getBoundingClientRect();const f=parent.document.querySelector("iframe.helloada-preview-frame").getBoundingClientRect();const x=f.x+r.x+r.width/2,y=f.y+r.y+r.height/2;const hit=parent.document.elementFromPoint(x,y);return {point:{x,y},tag:hit?.tagName,className:hit?.className,text:hit?.textContent?.trim().slice(0,120),optionsOpen:parent.document.querySelector(".helloada-preview-options")?.open}}')
    assert covered_target['optionsOpen'], ('expected preview options to still be open for covered-target diagnostic', covered_target)
    page.locator('.helloada-preview-options > summary').click()
    assert not page.locator('.helloada-preview-options').evaluate('(el)=>el.open'), ('summary click did not dismiss preview options', covered_target)
    target.hover()
    field_dialog = page.locator('.helloada-field-popover[role=dialog]')
    for width, height in viewports:
      page.set_viewport_size({'width': 1440, 'height': 900})
      page.mouse.move(4, 4)
      target.hover()
      overlay_button = page.locator('.helloada-preview-edit-overlay button')
      try:
        overlay_button.wait_for(timeout=5000)
      except Exception as error:
        target_hit = target.evaluate('(el)=>{const r=el.getBoundingClientRect();const frame=parent.document.querySelector("iframe.helloada-preview-frame").getBoundingClientRect();const x=frame.x+r.x+r.width/2,y=frame.y+r.y+r.height/2;const hit=parent.document.elementFromPoint(x,y);return {frameRect:frame.toJSON(),targetRect:r.toJSON(),pagePoint:{x,y},pageHit:{tag:hit?.tagName,className:hit?.className,text:hit?.textContent?.trim().slice(0,120),rect:hit?.getBoundingClientRect().toJSON()},options:parent.document.querySelector(".helloada-preview-options")?.outerHTML,optionsMenuRect:parent.document.querySelector(".helloada-preview-options > div")?.getBoundingClientRect().toJSON()}}')
        evidence = {
          'checkboxChecked': checkbox.is_checked(),
          'coveredTargetBeforeDismiss': covered_target,
          'optionsClosedAfterOutsideClick': not page.locator('.helloada-preview-options').evaluate('(el)=>el.open'),
          'preview': page.locator('iframe.helloada-preview-frame').evaluate('(el)=>({src:el.src,readyState:el.contentDocument?.readyState,field:el.contentDocument?.querySelector("[data-helloada-field=field-0]")?.outerHTML})'),
          'pageFieldCount': page.evaluate('()=>window.__pageFieldCount'),
          'targetHitTest': target_hit,
          'pointerEvents': page.locator('iframe.helloada-preview-frame').evaluate('(el)=>({count:el.contentWindow.__pointerEventCount,last:el.contentWindow.__lastPointerTarget})'),
          'overlay': page.locator('.helloada-preview-edit-overlay').count(),
          'workspaceText': page.locator('.helloada-workspace').inner_text()[:1200],
        }
        raise AssertionError(('quick-edit iframe overlay did not appear after real hover', evidence, str(error)))
      overlay_button.click()
      field_dialog.wait_for(timeout=5000)
      assert field_dialog.locator('textarea').input_value().startswith('Body 0'), ('field dialog did not open matching text entry', field_dialog.inner_text()[:500])
      page.set_viewport_size({'width': width, 'height': height})
      check_footer(field_dialog.locator('.helloada-field-popover-footer button'), height, 'field-dialog', width)
      check_overflow(field_dialog.locator('.helloada-field-popover-scroll'), 'field-dialog', width, height, (width, height) == (390, 480))
      outputs.append(f'field dialog {width}x{height}: overflowing body; footer hit-testable')
      page.screenshot(path=f'{root}/field-dialog-{width}x{height}.png', full_page=True)
      field_dialog.locator('.helloada-field-popover-footer button').first.click()
      assert not field_dialog.is_visible(), ('field dialog remains visible after close', width, height)

    # Exercise the separate full-page editing dialog through its own action.
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.locator('.helloada-preview-options summary').click()
    editor=page.locator('.helloada-page-editor')
    for width, height in viewports:
      page.set_viewport_size({'width': 1440, 'height': 900})
      page.get_by_role('button', name='owner.editManually').click()
      editor.wait_for()
      page.set_viewport_size({'width': width, 'height': height})
      check_footer(editor.locator('.helloada-page-editor-footer button'), height, 'page-editor', width)
      check_overflow(editor.locator('.helloada-page-editor-scroll'), 'page-editor', width, height, (width, height) == (390, 480))
      outputs.append(f'page editor {width}x{height}: overflowing body; footer hit-testable')
      page.screenshot(path=f'{root}/page-editor-{width}x{height}.png', full_page=True)
      editor.locator('.helloada-page-editor-footer button').first.click()
      assert not editor.is_visible(), ('page editor remains visible after close', width, height)

    # Exercise the real attachment input and component handlers against the
    # deterministic mocked HelloAda boundary; no component state is injected.
    for width, height in [(1440, 900), (390, 844)]:
      page.set_viewport_size({'width': width, 'height': height})
      page.reload()
      page.locator('.helloada-chat-form').wait_for()
      file_input = page.locator('.helloada-file-input')
      page.evaluate('() => { window.__holdUpload=true; window.__uploadMode="success" }')
      file_input.set_input_files({'name':'owner-image.png','mimeType':'image/png','buffer':b'\x89PNG\r\n\x1a\nfixture'})
      status=page.locator('.helloada-upload-status')
      status.get_by_text('Uploading').wait_for()
      assert status.get_by_text('owner-image.png').is_visible(), ('uploading status lacks filename', width)
      send=page.locator('.helloada-send-button')
      assert send.is_disabled(), ('send enabled during upload', width)
      assert page.evaluate('()=>window.__calls.some(c=>c.path==="/api/helloada/media/upload"&&c.method==="POST"&&c.file==="owner-image.png"&&c.fileType==="image/png"&&c.formFields.includes("file"))'), ('upload request did not use multipart file field', width)
      page.wait_for_function('()=>typeof window.__releaseUpload==="function" && window.__calls.some(c=>c.path==="/api/helloada/media/upload")')
      page.evaluate('()=>{window.__holdUpload=false;window.__releaseUpload()}')
      chip=page.get_by_role('button',name='Remove image owner-image.png')
      chip.get_by_text('Ready').wait_for()
      page.locator('#helloada-ada-message').fill('Review this image')
      send.click()
      page.wait_for_function('()=>window.__calls.some(c=>c.path==="/api/helloada/ada"&&c.method==="POST")')
      payload=page.evaluate('()=>window.__calls.find(c=>c.path==="/api/helloada/ada"&&c.method==="POST").body')
      assert payload['attachments']==[{'asset_id':731}], ('send payload did not contain the returned asset id exactly once', payload)
      outputs.append(f'attachments {width}x{height}: visible upload/ready, multipart file request, exact asset_id sent')

      # Upload a second file and remove its ready chip before sending. The next
      # ordinary click must not retain the removed asset in its payload.
      page.reload()
      page.locator('.helloada-chat-form').wait_for()
      file_input=page.locator('.helloada-file-input')
      send=page.locator('.helloada-send-button')
      page.evaluate('()=>{window.__calls=[];window.__holdUpload=false;window.__uploadMode="success"}')
      file_input.set_input_files({'name':'remove-me.png','mimeType':'image/png','buffer':b'\x89PNG\r\n\x1a\nfixture'})
      removed=page.get_by_role('button',name='Remove image owner-image.png')
      removed.get_by_text('Ready').wait_for()
      removed.click()
      page.locator('#helloada-ada-message').fill('Send without removed image')
      send.click()
      page.wait_for_function('()=>window.__calls.some(c=>c.path==="/api/helloada/ada"&&c.method==="POST")')
      payload=page.evaluate('()=>window.__calls.find(c=>c.path==="/api/helloada/ada"&&c.method==="POST").body')
      assert payload['attachments']==[], ('removed attachment remained in send payload', payload)

      # Unsupported files are visibly rejected without reaching upload.
      page.reload()
      page.locator('.helloada-chat-form').wait_for()
      file_input=page.locator('.helloada-file-input')
      send=page.locator('.helloada-send-button')
      page.evaluate('()=>window.__calls=[]')
      file_input.set_input_files({'name':'notes.txt','mimeType':'text/plain','buffer':b'not an image'})
      page.get_by_text('Unsupported file type').wait_for()
      assert not page.evaluate('()=>window.__calls.some(c=>c.path==="/api/helloada/media/upload")'), 'unsupported file reached upload boundary'

      # Simulated upload rejection is explicitly visible and blocks send; keep
      # the expected fixture failure classified separately from browser errors.
      page.evaluate('()=>{window.__calls=[];window.__uploadMode="failed"}')
      file_input.set_input_files({'name':'broken.png','mimeType':'image/png','buffer':b'\x89PNG\r\n\x1a\nfixture'})
      failed=page.locator('.helloada-upload-status')
      failed.get_by_text('Upload failed: Fixture upload rejected').wait_for()
      assert send.is_disabled(), 'send was not blocked after failed upload'
      assert page.evaluate('()=>window.__expectedFailure') == 'upload rejected: Fixture upload rejected', 'simulated upload failure was not classified'
      outputs.append(f'attachments {width}x{height}: unsupported and failed uploads visible; failure classified; removal omits asset')
    if errors: raise AssertionError('\n'.join(errors))
    (root/'browser-report.txt').write_text('\n'.join(outputs)+'\nNo console, page, HTTP, or request failures. Expected simulated failure: upload rejected: Fixture upload rejected.\n')
    browser.close()
finally: server.shutdown()
