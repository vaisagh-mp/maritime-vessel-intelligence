"""Domain-level exceptions and the DRF exception handler."""
import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("vessel_intel")


class DuplicateOpenOpportunityError(Exception):
    """Raised (internally, defensively) if a duplicate open Opportunity is ever attempted."""


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        return response

    logger.exception("Unhandled exception in %s", context.get("view"))
    return Response(
        {"detail": "An unexpected server error occurred."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
