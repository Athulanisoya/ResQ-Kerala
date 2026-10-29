"""Bound attachment uploads before multipart parsing in either ASGI app."""
import re
from starlette.responses import JSONResponse

_MAX_REQUEST_BYTES = 3 * 1024 * 1024 + 64 * 1024
_ATTACHMENT_POST = re.compile(r'^/(?:api|ui)/incidents/\d+/attachments$')

class AttachmentRequestLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'POST' or not _ATTACHMENT_POST.fullmatch(scope['path']):
            return await self.app(scope, receive, send)
        for key, value in scope.get('headers', []):
            if key.lower() == b'content-length':
                try:
                    size = int(value)
                except ValueError:
                    return await JSONResponse({'detail': 'Invalid content length'}, status_code=400)(scope, receive, send)
                if size < 0 or size > _MAX_REQUEST_BYTES:
                    return await JSONResponse({'detail': 'Attachment request is too large'}, status_code=413)(scope, receive, send)
        chunks, total = [], 0
        while True:
            event = await receive()
            if event['type'] == 'http.disconnect':
                return
            if event['type'] != 'http.request':
                continue
            chunk = event.get('body', b'')
            total += len(chunk)
            if total > _MAX_REQUEST_BYTES:
                return await JSONResponse({'detail': 'Attachment request is too large'}, status_code=413)(scope, receive, send)
            chunks.append(chunk)
            if not event.get('more_body', False):
                break
        body = b''.join(chunks)
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()
        return await self.app(scope, bounded_receive, send)
