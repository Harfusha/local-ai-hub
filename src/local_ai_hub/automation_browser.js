async (page) => {
  // INPUT is replaced with JSON data by the broker, never agent source code.
  const request = __LOCAL_AI_AUTOMATION_INPUT__;
  const context = page.context();
  const allowed = (value) => {
    try {
      const u = new URL(value);
      if (!['http:', 'https:'].includes(u.protocol) || u.username || u.password) return false;
      const host = u.hostname.replace(/^\[|\]$/g, '').toLowerCase();
      const port = Number(u.port || (u.protocol === 'https:' ? 443 : 80));
      const path = decodeURIComponent(u.pathname);
      return request.rules.some(([scheme, h, p, prefix]) =>
        u.protocol === scheme + ':' && host === h && port === p &&
        (prefix === '/' || path === prefix.replace(/\/$/, '') || path.startsWith(prefix.replace(/\/$/, '') + '/')));
    } catch { return false; }
  };
  const own = (p) => p._localHubAutomation === request.owner;
  const installGuard = async target => {
    if (target._localHubGuardPromise) return await target._localHubGuardPromise;
    if (target._localHubGuard) return;
    target._localHubGuardPromise = (async () => {
    const client = await context.newCDPSession(target);
    client.on('Fetch.requestPaused', async event => {
      const rejectDownload = code => {
        if (target._localHubDownloadFailure) return;
        target._localHubDownloadFailure = code;
        target._localHubDownloadRejected?.({error: code});
      };
      let stream;
      try {
        const responseStage = event.responseStatusCode !== undefined || event.responseErrorReason !== undefined;
        if (!responseStage) {
          if (event.resourceType === 'Document' && !allowed(event.request.url)) {
            if (target._localHubExpectDownload) rejectDownload('target_denied');
            await client.send('Fetch.failRequest', {requestId: event.requestId, errorReason: 'BlockedByClient'});
          } else {
            await client.send('Fetch.continueRequest', {requestId: event.requestId,
              interceptResponse: Boolean(target._localHubExpectDownload)});
          }
          return;
        }
        if (!target._localHubExpectDownload || event.responseErrorReason ||
            [301, 302, 303, 307, 308].includes(event.responseStatusCode)) {
          await client.send('Fetch.continueResponse', {requestId: event.requestId});
          return;
        }
        // Bound the original response stream before Chrome writes a download.
        // Never replay its URL with another request or wait for saveAs to finish.
        const headers = event.responseHeaders || [];
        const declared = headers.find(h => h.name.toLowerCase() === 'content-length');
        if (declared && /^\d+$/.test(declared.value) && Number(declared.value) > request.maxBinaryBytes) {
          rejectDownload('download_size_limit');
          await client.send('Fetch.failRequest', {requestId: event.requestId, errorReason: 'BlockedByClient'});
          return;
        }
        ({stream} = await client.send('Fetch.takeResponseBodyAsStream', {requestId: event.requestId}));
        const chunks = [];
        let length = 0;
        while (true) {
          const part = await client.send('IO.read', {handle: stream, size: Math.min(65536, request.maxBinaryBytes - length + 1)});
          const bytes = Buffer.from(part.data, part.base64Encoded ? 'base64' : 'utf8');
          length += bytes.length;
          if (length > request.maxBinaryBytes) {
            rejectDownload('download_size_limit');
            await client.send('Fetch.failRequest', {requestId: event.requestId, errorReason: 'BlockedByClient'});
            return;
          }
          chunks.push(bytes);
          if (part.eof) break;
        }
        const body = Buffer.concat(chunks, length);
        const responseHeaders = headers.filter(h => !['content-length', 'content-encoding', 'transfer-encoding'].includes(h.name.toLowerCase()));
        responseHeaders.push({name: 'Content-Length', value: String(length)});
        await client.send('Fetch.fulfillRequest', {requestId: event.requestId, responseCode: event.responseStatusCode,
          responseHeaders, body: body.toString('base64')});
      } catch {
        if (target._localHubExpectDownload) rejectDownload('download_transport_failed');
        try { await client.send('Fetch.failRequest', {requestId: event.requestId, errorReason: 'Failed'}); } catch {}
      } finally {
        if (stream) { try { await client.send('IO.close', {handle: stream}); } catch {} }
      }
    });
    await client.send('Fetch.enable', {patterns: [{urlPattern: '*', requestStage: 'Request'}]});
    // This transport has one broker owner. Its fixed dialog policy replaces the
    // upstream MCP modal handler, whose early modal response drops code results.
    target.removeAllListeners('dialog');
    target.on('dialog', async dialog => {
      const decision = target._localHubNextDialog || {accept: false};
      target._localHubNextDialog = null;
      target._localHubLastDialog = {type: dialog.type(), message: dialog.message().slice(0, request.maxChars), accepted: decision.accept};
      try { if (decision.accept) await dialog.accept(decision.text || ''); else await dialog.dismiss(); } catch {}
    });
    target.on('download', download => {
      if (!target._localHubExpectDownload) download.cancel().catch(() => {});
    });
    target._localHubGuard = client;
    })();
    return await target._localHubGuardPromise;
  };
  const fail = (code, unknown = false) => JSON.stringify({success: false, error_code: code,
    error: 'Browser target or operation is outside the owned capability', outcome_unknown: unknown});
  let p = context.pages().find(p => own(p) && p._localHubTab === request.tab);
  if (request.initialize) {
    if (page._localHubAutomation && !own(page)) return fail('target_owned');
    if (request.mode === 'extension' && (!allowed(page.url()) || page.url() !== request.initialUrl)) return fail('target_mismatch');
    page._localHubAutomation = request.owner;
    page._localHubTab = request.tab;
    p = page;
    await installGuard(page);
    await context.route('**/*', async route => {
      const req = route.request();
      let target;
      try { target = req.frame().page(); } catch { return route.continue(); }
      let scoped = own(target);
      if (!scoped) {
        const opener = await target.opener();
        scoped = opener && own(opener);
        if (scoped) {
          target._localHubAutomation = request.owner;
          target._localHubTab = 'popup-' + (++page._localHubSequence);
          await installGuard(target);
        }
      }
      if (scoped && req.isNavigationRequest() && !allowed(req.url())) return route.abort('blockedbyclient');
      return route.continue();
    });
    page._localHubSequence = 0;
    context.on('page', target => {
      target.opener().then(async opener => {
        if (opener && own(opener)) {
          target._localHubAutomation = request.owner;
          target._localHubTab ||= 'popup-' + (++page._localHubSequence);
          await installGuard(target);
        }
      }).catch(() => {});
    });
    if (request.mode === 'isolated') await p.goto(request.initialUrl, {timeout: request.timeout, waitUntil: 'domcontentloaded'});
  }
  if (!p || p.isClosed()) return fail('target_gone');
  if (!allowed(p.url())) return fail('target_changed');
  p.setDefaultTimeout(request.timeout);
  p.setDefaultNavigationTimeout(request.timeout);
  const a = request.arguments;
  const css = selector => p.locator('css=' + selector);
  const locator = () => css(a.selector);
  let result = {};
  switch (a.command) {
    case 'snapshot':
      result = {title: await p.title(), text: (await p.locator('body').ariaSnapshot()).slice(0, request.maxChars),
        last_dialog: p._localHubLastDialog || null};
      break;
    case 'navigate':
      if (!allowed(a.url)) return fail('target_denied');
      await p.goto(a.url, {waitUntil: 'domcontentloaded'}); break;
    case 'click': await locator().click(); break;
    case 'fill': await locator().fill(a.text); break;
    case 'press': await locator().press(a.key); break;
    case 'select': await locator().selectOption(a.option); break;
    case 'check': await locator().setChecked(a.checked); break;
    case 'hover': await locator().hover(); break;
    case 'drag': await locator().dragTo(css(a.destination)); break;
    case 'scroll': await p.mouse.wheel(a.x || 0, a.y || 0); break;
    case 'dialog': p._localHubNextDialog = {accept: a.accept, text: a.text || ''}; result = {next_dialog: a.accept ? 'accept' : 'dismiss'}; break;
    case 'upload': await locator().setInputFiles(a.files); break;
    case 'download': {
      p._localHubExpectDownload = true;
      p._localHubDownloadFailure = null;
      let downloadListener;
      const pending = new Promise(resolve => {
        downloadListener = download => resolve({download});
        p.once('download', downloadListener);
      });
      const rejected = new Promise(resolve => { p._localHubDownloadRejected = resolve; });
      try {
      try { await locator().click(); } catch (error) {
        if (p._localHubDownloadFailure) return fail(p._localHubDownloadFailure);
        throw error;
      }
      const outcome = await Promise.race([pending, rejected]);
      if (outcome.error) return fail(outcome.error);
      const download = outcome.download;
      if (!allowed(download.url())) {
        await download.cancel();
        return fail('target_denied');
      }
      await download.saveAs(request.outputFile);
      result = {artifact_path: request.outputFile, mime_type: 'application/octet-stream',
        suggested_filename: download.suggestedFilename().slice(0, 160)};
      } finally {
        p._localHubExpectDownload = false;
        p._localHubDownloadRejected = null;
        p.removeListener('download', downloadListener);
      }
      break;
    }
    case 'screenshot':
      await p.screenshot({path: request.outputFile, type: 'png', mask: [p.locator('iframe')], timeout: request.timeout});
      result = {artifact_path: request.outputFile, mime_type: 'image/png'}; break;
    case 'tabs':
      result = {tabs: context.pages().filter(q => own(q) && allowed(q.url())).map(q => ({tab_id: q._localHubTab, url: q.url()}))}; break;
    case 'new_tab': {
      if (!allowed(a.url)) return fail('target_denied');
      const target = await context.newPage();
      target._localHubAutomation = request.owner;
      target._localHubTab = 'tab-' + (++page._localHubSequence);
      await installGuard(target);
      await target.goto(a.url, {timeout: request.timeout, waitUntil: 'domcontentloaded'});
      if (!allowed(target.url())) return fail('target_changed', true);
      result = {tab_id: target._localHubTab}; break;
    }
    case 'switch_tab': {
      const target = context.pages().find(q => own(q) && q._localHubTab === a.destination && allowed(q.url()));
      if (!target) return fail('target_denied');
      result = {tab_id: target._localHubTab}; break;
    }
    case 'close_tab':
      if (p._localHubTab === 'main') return fail('use_session_close');
      await p.close(); return JSON.stringify({closed: true});
    default: return fail('unsupported_command');
  }
  if (!allowed(p.url())) return fail('target_changed', true);
  return JSON.stringify({...result, url: p.url(), tab_id: result.tab_id || p._localHubTab});
}
