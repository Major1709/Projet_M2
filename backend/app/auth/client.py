import json
from typing import Any, Final
from urllib.parse import urlencode, urlsplit

import httpx2

from app.auth.domain import (
    ATLASSIAN_ACCESSIBLE_RESOURCES,
    ATLASSIAN_AUTHORIZE_ENDPOINT,
    ATLASSIAN_ME_ENDPOINT,
    ATLASSIAN_OAUTH_TOKEN_ENDPOINT,
    ATLASSIAN_SCOPES,
    AtlassianSite,
    code_challenge_for,
)
from app.auth.errors import NoSiteGranted, ProviderRefused
from app.mcp.adapters.http_guard import (
    EndpointResolver,
    PinnedAddressTransport,
    SystemEndpointResolver,
    bounded_response_hook,
    is_approved_public_address,
    validate_fixed_endpoint,
)

HTTPS_PORT: Final = 443
CALL_TIMEOUT_SECONDS: Final = 15.0
# Generous for a token document and a short site list, and far below anything that
# could exhaust memory. Consent responses are small.
MAX_RESPONSE_BYTES: Final = 256 * 1024

# Validated at import, like every other fixed destination in this codebase: a typo
# that downgraded the scheme would otherwise only surface at sign-in time.
for _endpoint in (
    ATLASSIAN_AUTHORIZE_ENDPOINT,
    ATLASSIAN_OAUTH_TOKEN_ENDPOINT,
    ATLASSIAN_ACCESSIBLE_RESOURCES,
    ATLASSIAN_ME_ENDPOINT,
):
    validate_fixed_endpoint(_endpoint)


def authorization_url(*, client_id: str, redirect_uri: str, state: str, verifier: str) -> str:
    """The consent URL the browser is sent to.

    ``prompt=consent`` on purpose: without it Atlassian may silently reuse an earlier
    grant, and the user never sees the site chooser -- which is the one screen that
    decides which site the resulting token covers.
    """

    query = urlencode(
        {
            "audience": "api.atlassian.com",
            "client_id": client_id,
            "scope": ATLASSIAN_SCOPES,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            "prompt": "consent",
            "code_challenge": code_challenge_for(verifier),
            "code_challenge_method": "S256",
        }
    )
    return f"{ATLASSIAN_AUTHORIZE_ENDPOINT}?{query}"


class AtlassianOAuthClient:
    """The three outbound calls a sign-in makes, under the project's transport rules.

    HTTPS only, port fixed, redirects refused, ambient proxy configuration ignored,
    the resolved address pinned with the hostname preserved for SNI, and the response
    bounded. The same discipline the MCP reads and the model calls already follow --
    an authorization code and a refresh token deserve at least as much.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        transport: httpx2.AsyncBaseTransport | None = None,
        resolver: EndpointResolver | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        # An injected transport wins, so the tests never touch the network.
        self._transport = transport
        self._resolver = resolver or SystemEndpointResolver()

    async def exchange_code(self, *, code: str, verifier: str) -> dict[str, Any]:
        payload = {
            "grant_type": "authorization_code",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "redirect_uri": self._redirect_uri,
            "code_verifier": verifier,
        }
        document = await self._post_form(ATLASSIAN_OAUTH_TOKEN_ENDPOINT, payload)
        for key in ("access_token", "refresh_token"):
            if not isinstance(document.get(key), str) or not document[key]:
                # A grant without a refresh token means offline_access was not
                # granted, and the deployment would be back at consent within the
                # hour. Better to fail now, while the user is still here.
                raise ProviderRefused()
        return document

    async def granted_site(self, access_token: str) -> AtlassianSite:
        """The single site this token covers.

        A delegated Atlassian token covers exactly the site chosen on the consent
        screen, and nothing in the token says which. This call is the only way to
        learn it -- and the reason the tenant can be derived rather than declared.
        """

        payload = await self._get(ATLASSIAN_ACCESSIBLE_RESOURCES, access_token)
        if not isinstance(payload, list) or not payload:
            raise NoSiteGranted()
        first = payload[0]
        if not isinstance(first, dict) or not first.get("id") or not first.get("url"):
            raise NoSiteGranted()
        return AtlassianSite(cloud_id=str(first["id"]), url=str(first["url"]))

    async def account_id(self, access_token: str) -> str:
        payload = await self._get(ATLASSIAN_ME_ENDPOINT, access_token)
        if not isinstance(payload, dict) or not payload.get("account_id"):
            raise ProviderRefused()
        return str(payload["account_id"])

    async def _post_form(self, endpoint: str, form: dict[str, str]) -> dict[str, Any]:
        async with await self._client_for(endpoint) as client:
            try:
                response = await client.post(
                    endpoint,
                    data=form,
                    headers={"Accept": "application/json"},
                )
            except httpx2.HTTPError as error:
                raise ProviderRefused() from error
        return self._document(response)

    async def _get(self, endpoint: str, access_token: str) -> Any:
        async with await self._client_for(endpoint) as client:
            try:
                response = await client.get(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                )
            except httpx2.HTTPError as error:
                raise ProviderRefused() from error
        return self._parsed(response)

    @staticmethod
    def _document(response: httpx2.Response) -> dict[str, Any]:
        document = AtlassianOAuthClient._parsed(response)
        if not isinstance(document, dict):
            raise ProviderRefused()
        return document

    @staticmethod
    def _parsed(response: httpx2.Response) -> Any:
        if response.status_code != 200:
            # The body is deliberately dropped. It can echo the code, name the client,
            # or describe the failure in terms written for an operator.
            raise ProviderRefused()
        try:
            return json.loads(response.content)
        except ValueError as error:
            raise ProviderRefused() from error

    async def _client_for(self, endpoint: str) -> httpx2.AsyncClient:
        hostname = urlsplit(endpoint).hostname or ""
        transport = self._transport
        if transport is None:
            transport = PinnedAddressTransport(
                hostname=hostname,
                address=await self._approved_address(hostname),
            )
        return httpx2.AsyncClient(
            timeout=CALL_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            event_hooks={"response": [bounded_response_hook(MAX_RESPONSE_BYTES)]},
        )

    async def _approved_address(self, hostname: str) -> str:
        """Resolve once, approve, and connect to that address.

        Connecting by hostname would resolve a second time inside the client, and the
        second answer is the one that actually gets dialled -- so the check would
        guard a resolution nobody used.
        """

        try:
            addresses = await self._resolver.resolve(hostname=hostname, port=HTTPS_PORT)
        except OSError as error:
            raise ProviderRefused() from error
        approved = [address for address in addresses if is_approved_public_address(address)]
        if not approved:
            raise ProviderRefused()
        return approved[0]
