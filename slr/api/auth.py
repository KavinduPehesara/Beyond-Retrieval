"""Google OpenID Connect with browser-bound state and one-use login tickets."""
import base64
import hashlib
import hmac
import os
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlencode
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from google.oauth2 import id_token
from google.auth.transport.requests import Request as GoogleRequest
from slr.services import accounts

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

router = APIRouter(prefix="/auth")
bearer = HTTPBearer(auto_error=False)

def optional_account(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None:
        return None
    try:
        return accounts.authenticate(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(401, str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc

def current_account(account=Depends(optional_account)):
    if account is None:
        raise HTTPException(401, "Sign in to access saved reviews")
    return account

def config():
    return {"client_id": os.getenv("GOOGLE_CLIENT_ID", ""), "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""), "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/auth/google/callback"), "dashboard": os.getenv("DASHBOARD_URL", "http://127.0.0.1:8501/Run_a_Review")}

@router.get("/config")
def auth_config():
    cfg = config()
    return {"configured": bool(cfg["client_id"] and cfg["client_secret"])}

@router.get("/google/start")
def google_start():
    cfg = config()
    if not auth_config()["configured"]:
        raise HTTPException(503, "Google sign-in needs OAuth credentials in .env.")
    state, nonce, verifier = accounts.begin()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    response = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(dict(client_id=cfg["client_id"], redirect_uri=cfg["redirect_uri"], response_type="code", scope="openid email profile", state=state, nonce=nonce, code_challenge=challenge, code_challenge_method="S256", prompt="select_account")))
    response.set_cookie("br_oauth_state", state, max_age=600, httponly=True, secure=cfg["redirect_uri"].startswith("https:"), samesite="lax", path="/auth")
    response.headers["Cache-Control"] = "no-store"
    return response

@router.get("/google/callback")
def google_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    cookie = request.cookies.get("br_oauth_state", "")
    if not state or not cookie or not hmac.compare_digest(state, cookie):
        raise HTTPException(400, "Sign-in state mismatch. Start sign-in again.")
    try:
        nonce, verifier = accounts.consume_state(state)
        if error or not code:
            raise ValueError("Google sign-in was cancelled. Return to the dashboard and try again.")
        cfg = config()
        result = httpx.post("https://oauth2.googleapis.com/token", data=dict(code=code, client_id=cfg["client_id"], client_secret=cfg["client_secret"], redirect_uri=cfg["redirect_uri"], grant_type="authorization_code", code_verifier=verifier), timeout=20)
        result.raise_for_status()
        claims = id_token.verify_oauth2_token(result.json()["id_token"], GoogleRequest(), cfg["client_id"])
        if not hmac.compare_digest(claims.get("nonce", ""), nonce):
            raise ValueError("Invalid Google sign-in nonce.")
        ticket, binding = accounts.issue_ticket(claims)
    except (ValueError, KeyError, httpx.HTTPError) as exc:
        raise HTTPException(400, "Google sign-in could not complete. Please start again.") from exc
    response = RedirectResponse(cfg["dashboard"] + "?login_ticket=" + ticket, status_code=303)
    response.delete_cookie("br_oauth_state", path="/auth")
    response.set_cookie("br_login_binding", binding, max_age=120, httponly=True, secure=cfg["dashboard"].startswith("https:"), samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

class Ticket(BaseModel):
    ticket: str = Field(min_length=1, max_length=200)
    binding: str = Field(min_length=1, max_length=200)

@router.post("/exchange")
def exchange(req: Ticket):
    try:
        return JSONResponse(accounts.exchange_ticket(req.ticket, req.binding), headers={"Cache-Control": "no-store"})
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc

@router.post("/logout")
def logout(account=Depends(current_account), credentials=Depends(bearer)):
    accounts.logout(credentials.credentials)
    return {"signed_out": True}
