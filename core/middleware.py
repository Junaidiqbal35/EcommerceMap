from django.core.exceptions import MiddlewareNotUsed
import sys
import logging

logger = logging.getLogger(__name__)

class BrokenPipeMiddleware:
    """
    Middleware to handle broken pipe errors gracefully
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        try:
            response = self.get_response(request)
            return response
        except BrokenPipeError:
            # Client disconnected - log but don't crash
            logger.warning(
                f"Broken pipe from {request.META.get('REMOTE_ADDR')} "
                f"on {request.path}"
            )
            # Return None to indicate connection closed
            return None
        except Exception as e:
            # Re-raise other exceptions
            raise
    
    def process_exception(self, request, exception):
        """Handle broken pipe in exception processing"""
        if isinstance(exception, BrokenPipeError):
            logger.warning(
                f"Broken pipe (exception) from {request.META.get('REMOTE_ADDR')}"
            )
            return None
        return None
