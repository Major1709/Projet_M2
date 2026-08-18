class SignInError(Exception):
    """A sign-in that cannot complete. Messages here reach the browser."""

    code = "SIGN_IN_FAILED"
    safe_message = "Sign-in could not be completed"


class SignInDisabled(SignInError):
    code = "SIGN_IN_DISABLED"
    safe_message = "Sign-in with Atlassian is not enabled"


class AuthorizationExpired(SignInError):
    code = "AUTHORIZATION_EXPIRED"
    safe_message = "This sign-in attempt is no longer valid. Start again."


class ProviderRefused(SignInError):
    """The provider rejected the exchange. Its body is never forwarded.

    It can carry the code, the client secret echoed back, or an error description
    written for an operator -- none of which belongs in a browser.
    """

    code = "PROVIDER_REFUSED"
    safe_message = "Atlassian refused the sign-in"


class NoSiteGranted(SignInError):
    """Consent succeeded but covers no site, so nothing can be read afterwards."""

    code = "NO_SITE_GRANTED"
    safe_message = "No Atlassian site was granted. Choose a site on the consent screen."
