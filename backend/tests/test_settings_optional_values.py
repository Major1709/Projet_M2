"""Compose substitutes an unresolved variable with an empty string. These hold the
line between "not set", which is ordinary, and "set to something wrong", which is
not and must still stop the process.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize(
    "field",
    ["atlassian_oauth_client_id", "atlassian_oauth_redirect_uri", "atlassian_expected_cloud_id"],
)
def test_an_empty_optional_reads_as_absent(field: str) -> None:
    settings = Settings(environment="test", **{field: ""})

    assert getattr(settings, field) is None


def test_an_empty_client_id_still_blocks_sign_in_rather_than_half_enabling_it() -> None:
    # Reading empty as absent must not become a way to turn the flow on without
    # credentials: the guard that requires all three still fires.
    with pytest.raises(ValidationError):
        Settings(
            environment="test",
            atlassian_oauth_enabled=True,
            atlassian_oauth_client_id="",
            atlassian_oauth_client_secret_file="/run/secrets/x",
            atlassian_oauth_redirect_uri="https://app.test/callback",
        )
