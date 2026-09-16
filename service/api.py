"""HTTP API. Agent/operator routes and customer approval routes are separate."""
import secrets
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from service.core import CartlyService
from service.errors import ServiceError


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Body):
    user_id: str
    email: str | None = None
    phone: str | None = None


class Request(Body):
    intent: Literal["return", "cancel", "address", "coupon", "safety", "legal", "human", "uncovered"]
    order_id: str | None = None
    item_id: str | None = None
    reason: Literal["change_of_mind", "damaged", "defective", "wrong_item"] | None = None
    address: dict[str, str] | None = None


class Tool(Body):
    arguments: dict = Field(default_factory=dict)


class Message(Body):
    content: str = Field(min_length=1, max_length=10000)


class Condition(Body):
    order_id: str
    item_id: str
    unused: StrictBool


class Acceptance(Body):
    terms_hash: str
    accept: StrictBool


def create_app(repository, operator_key, world_id="development", model_transport=None):
    if not operator_key or len(operator_key) < 32:
        raise ValueError("A server-side operator key of at least 32 characters is required")
    service = CartlyService(repository)
    app = FastAPI(title="Cartly v0.1 — guarded support API", version="0.1.0",
                  description="Persistent sandbox orders, policy decisions, customer approval and atomic actions. All dates use the seed config.")
    app.state.service = service
    app.state.repository = repository
    bearer = HTTPBearer(auto_error=False)

    def customer(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if not credentials:
            raise ServiceError("unauthorized", "Valid session authentication required", 401)
        return credentials.credentials

    def operator(x_cartly_service_key: Annotated[str | None, Header()] = None):
        if not x_cartly_service_key or not secrets.compare_digest(x_cartly_service_key, operator_key):
            raise ServiceError("operator_required", "Server authentication required", 401)

    def request_key(idempotency_key: Annotated[str, Header(min_length=1, max_length=128)]):
        return idempotency_key

    token = Annotated[str, Depends(customer)]
    key = Annotated[str, Depends(request_key)]
    private = [Depends(operator)]

    @app.exception_handler(ServiceError)
    async def handle_error(request, exc):
        return JSONResponse(exc.response(), status_code=exc.status)

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health")
    def health():
        with repository.connect() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "version": "0.1.0", "storage": "postgresql", "mode": "guarded"}

    @app.post("/v1/sessions", dependencies=private)
    def login(body: Login):
        return service.login(world_id, **body.model_dump())

    @app.get("/v1/session")
    def session(auth: token):
        return service.view(auth)

    @app.post("/v1/chat")
    def chat(body: Message, auth: token, request_id: key):
        if model_transport is None:
            raise ServiceError("model_disabled", "Live model calls are disabled. Start with --enable-model to opt in", 503)
        from service.agent import PersistentAgent
        return PersistentAgent(service, model_transport).reply(auth, body.content, request_id)

    @app.post("/v1/messages")
    def message(body: Message, auth: token, request_id: key):
        return service.message(auth, body.content, request_id)

    @app.post("/v1/condition")
    def condition(body: Condition, auth: token, request_id: key):
        return service.assert_unused(auth, **body.model_dump(), key=request_id)

    @app.post("/v1/proposals/{proposal_id}/acceptance")
    def accept(proposal_id: str, body: Acceptance, auth: token, request_id: key):
        return service.accept(auth, proposal_id, **body.model_dump(), key=request_id)

    @app.post("/v1/tools/{tool_name}", dependencies=private)
    def tool(tool_name: str, body: Tool, auth: token):
        return service.tool(auth, tool_name, body.arguments)

    @app.post("/v1/decisions", dependencies=private)
    def decision(body: Request, auth: token):
        return service.decision(auth, body.model_dump(exclude_none=True))

    @app.post("/v1/proposals", dependencies=private)
    def propose(body: Request, auth: token, request_id: key):
        return service.propose(auth, body.model_dump(exclude_none=True), request_id)

    @app.post("/v1/proposals/{proposal_id}/execute", dependencies=private)
    def execute(proposal_id: str, auth: token, request_id: key):
        return service.execute(auth, proposal_id, request_id)

    @app.post("/v1/system/pickups/{return_id}/complete", dependencies=private)
    def pickup(return_id: str, auth: token, request_id: key):
        return service.pickup(auth, return_id, request_id)

    @app.get("/v1/audit", dependencies=private)
    def audit():
        return repository.verify_audit(world_id)

    from service.web import install
    install(app, service, operator, customer, model_transport, world_id)
    return app
