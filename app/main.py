"""FastAPI application: auth, task CRUD, AI summary, and the static frontend."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import ai, models, schemas
from .auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from .database import Base, engine, get_db

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="AI-Powered Task Manager",
    description="Task manager with JWT auth and an AI-generated summary/priority order.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------- auth
@app.post(
    "/api/auth/register",
    response_model=schemas.UserOut,
    status_code=status.HTTP_201_CREATED,
    tags=["auth"],
)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    if db.scalar(select(models.User).where(models.User.username == payload.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    user = models.User(
        username=payload.username, password_hash=hash_password(payload.password)
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:  # two simultaneous registrations of the same name
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken") from None
    db.refresh(user)
    return user


@app.post("/api/auth/login", response_model=schemas.Token, tags=["auth"])
def login(
    form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = db.scalar(select(models.User).where(models.User.username == form.username))
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return schemas.Token(access_token=create_access_token(user.username))


@app.get("/api/auth/me", response_model=schemas.UserOut, tags=["auth"])
def me(user: models.User = Depends(get_current_user)):
    return user


# --------------------------------------------------------------- tasks
def _get_owned_task(db: Session, task_id: int, user: models.User) -> models.Task:
    task = db.scalar(
        select(models.Task).where(
            models.Task.id == task_id, models.Task.owner_id == user.id
        )
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return task


@app.get("/api/tasks", response_model=list[schemas.TaskOut], tags=["tasks"])
def list_tasks(
    status_filter: schemas.Status | None = Query(default=None, alias="status"),
    priority: schemas.Priority | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    query = select(models.Task).where(models.Task.owner_id == user.id)
    if status_filter:
        query = query.where(models.Task.status == status_filter)
    if priority:
        query = query.where(models.Task.priority == priority)
    return db.scalars(query.order_by(models.Task.id.desc())).all()


@app.post(
    "/api/tasks",
    response_model=schemas.TaskOut,
    status_code=status.HTTP_201_CREATED,
    tags=["tasks"],
)
def create_task(
    payload: schemas.TaskCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    task = models.Task(**payload.model_dump(), owner_id=user.id)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@app.get("/api/tasks/{task_id}", response_model=schemas.TaskOut, tags=["tasks"])
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return _get_owned_task(db, task_id, user)


@app.put("/api/tasks/{task_id}", response_model=schemas.TaskOut, tags=["tasks"])
def update_task(
    task_id: int,
    payload: schemas.TaskUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    task = _get_owned_task(db, task_id, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is None and field != "due_date":
            continue  # only due_date may be cleared
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


@app.delete(
    "/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["tasks"]
)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    task = _get_owned_task(db, task_id, user)
    db.delete(task)
    db.commit()


# ------------------------------------------------------------------ AI
@app.post("/api/ai/summary", response_model=schemas.SummaryOut, tags=["ai"])
def ai_summary(
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    open_tasks = db.scalars(
        select(models.Task).where(
            models.Task.owner_id == user.id, models.Task.status != "done"
        )
    ).all()
    payload = [
        {
            "id": t.id,
            "title": t.title,
            "priority": t.priority,
            "status": t.status,
            "due_date": t.due_date,
        }
        for t in open_tasks
    ]
    return ai.summarize_tasks(payload)


# Must be registered last so it doesn't shadow the /api routes.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
