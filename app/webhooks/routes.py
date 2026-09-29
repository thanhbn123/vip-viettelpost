from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.webhooks.dependencies import get_vtp_webhook_processor
from app.webhooks.processor import WebhookOutcome, WebhookProcessor, WebhookResultKind
from app.webhooks.viettel_post_payload import RejectionKind

router = APIRouter()


@router.post("/viettel-post")
async def viettel_post_webhook(
    request: Request,
    processor: Annotated[WebhookProcessor, Depends(get_vtp_webhook_processor)],
) -> JSONResponse:
    # Reject oversized bodies before reading them when the client declares the length.
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > processor.max_body_bytes:
        outcome = WebhookOutcome(
            kind=WebhookResultKind.REJECTED,
            http_status=413,
            rejection=RejectionKind.PAYLOAD_TOO_LARGE,
            detail="body exceeds limit",
        )
    else:
        # The processor does blocking database I/O: keep it off the event loop.
        outcome = await run_in_threadpool(processor.process, await request.body())
    return JSONResponse(status_code=outcome.http_status, content=outcome.response_body())
