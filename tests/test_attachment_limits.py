"""Streaming and declared-length requests are rejected before multipart parsing."""
import asyncio
from backend.utils.attachment_limits import AttachmentRequestLimit, _MAX_REQUEST_BYTES


def test_streaming_body_limit_does_not_call_inner_application():
    called = []
    sent = []
    chunks = [b'x' * (1024 * 1024)] * 4
    async def application(scope, receive, send):
        called.append(True)
    async def receive():
        chunk = chunks.pop(0)
        return {'type':'http.request','body':chunk,'more_body':bool(chunks)}
    async def send(event): sent.append(event)
    scope = {'type':'http','method':'POST','path':'/api/incidents/1/attachments','headers':[]}
    asyncio.run(AttachmentRequestLimit(application)(scope, receive, send))
    assert not called and sent[0]['status'] == 413


def test_declared_length_rejected_without_reading_body():
    called=[]; sent=[]
    async def application(scope, receive, send): called.append(True)
    async def receive(): raise AssertionError('Oversized declared body must not be read')
    async def send(event): sent.append(event)
    scope={'type':'http','method':'POST','path':'/ui/incidents/1/attachments','headers':[(b'content-length',str(_MAX_REQUEST_BYTES+1).encode())]}
    asyncio.run(AttachmentRequestLimit(application)(scope,receive,send))
    assert not called and sent[0]['status'] == 413
