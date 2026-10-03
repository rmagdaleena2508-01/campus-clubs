import asyncio
from dataclasses import dataclass

from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.config import settings
from app.errors import AppError, NotAuthenticated

GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str
    picture: str | None


def _verify(token: str) -> GoogleIdentity:
    if not settings.GOOGLE_CLIENT_ID:
        raise AppError("Google sign-in is not configured.", 503)
    try:
        claims = id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
    except (ValueError, GoogleAuthError):
        raise NotAuthenticated("Google sign-in failed. Please try again.")

    if claims.get("iss") not in GOOGLE_ISSUERS or not claims.get("email_verified"):
        raise NotAuthenticated("Google sign-in failed. Please try again.")

    email = claims["email"].strip().lower()
    # hd is only present for Google Workspace accounts, so a personal Gmail can never pass
    if claims.get("hd") != settings.COLLEGE_DOMAIN or not email.endswith("@" + settings.COLLEGE_DOMAIN):
        raise NotAuthenticated(f"Use your @{settings.COLLEGE_DOMAIN} account to sign in.")

    return GoogleIdentity(
        sub=claims["sub"],
        email=email,
        name=(claims.get("name") or email.split("@")[0]).strip(),
        picture=claims.get("picture"),
    )


async def verify_google_token(token: str) -> GoogleIdentity:
    # google-auth is blocking (it fetches Google's public keys), so keep it off the event loop
    return await asyncio.to_thread(_verify, token)
