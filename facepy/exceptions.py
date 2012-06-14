class FacepyError(Exception):
    """Base class for exceptions raised by Facepy."""


class FacebookError(FacepyError):
    """Exception for errors returned by the Graph API."""

    def __init__(self, message, code):
        super(FacebookError, self).__init__(message)

        self.code = code


class OAuthError(FacebookError):
    """Exception for errors specifically related to OAuth."""


class HTTPError(FacepyError):
    """Exception for transport errors."""
