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


class AmbiguousSiteGrant(SignInError):
    """Consent covers several sites and nothing says which one is the tenant.

    Refused rather than resolved by taking the first: the order of that list is not
    part of any contract, and the tenant is the boundary every permission in this
    system rests on. A deployment that legitimately faces several sites pins one
    with ``PKA_ATLASSIAN_EXPECTED_CLOUD_ID``.
    """

    code = "AMBIGUOUS_SITE_GRANT"
    safe_message = (
        "This grant covers several Atlassian sites. "
        "Authorise a single site, or ask an administrator to pin the expected one."
    )


class UnexpectedSiteGranted(SignInError):
    """The deployment pinned a site and consent produced a different one."""

    code = "UNEXPECTED_SITE_GRANTED"
    safe_message = "The authorised Atlassian site is not the one this deployment expects."
