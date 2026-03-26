import os
from datetime import datetime, date

from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app import crud
from app.utils import save_upload_file, ensure_upload_dir

Base.metadata.create_all(bind=engine)
ensure_upload_dir()

app = FastAPI(title="ImmoFlow")
app.add_middleware(SessionMiddleware, secret_key="immoflow_test_secret_key_123456")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return crud.get_user_by_id(db, user_id)


def require_login(request: Request, db: Session):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt")
    return user


def get_task_priority(task):
    today = date.today()

    if task.due_date is None:
        return "Keine Frist", ""

    if task.due_date < today:
        return "Überfällig", "red"

    days_left = (task.due_date - today).days

    if days_left <= 3:
        return "In den nächsten 3 Tagen fällig", "red"

    if days_left <= 7:
        return "In 4 bis 7 Tagen fällig", "yellow"

    return "Später fällig", ""


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"error": ""}
    )


@app.post("/register", response_class=HTMLResponse)
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    existing_user = crud.get_user_by_username(db, username)
    if existing_user:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Benutzername existiert bereits"}
        )

    user = crud.create_user(db, username=username, password=password)
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": ""}
    )


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = crud.authenticate_user(db, username, password)

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Falscher Benutzername oder Passwort"}
        )

    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    search: str = "",
    done_search: str = "",
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    buildings = crud.get_all_buildings(db, user_id=user.id, search=search)
    open_tasks = crud.get_open_tasks_sorted(db, user_id=user.id)

    tasks_with_priority = []
    for task in open_tasks:
        priority_text, priority_class = get_task_priority(task)
        tasks_with_priority.append({
            "task": task,
            "priority_text": priority_text,
            "priority_class": priority_class
        })

    done_buildings = crud.get_all_buildings(db, user_id=user.id, search=done_search)
    done_matches = []

    for building in done_buildings:
        done_tasks = [task for task in building.tasks if task.status == "erledigt"]
        if done_tasks:
            done_matches.append({
                "building": building,
                "tasks": done_tasks
            })

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "buildings": buildings,
            "search": search,
            "tasks_with_priority": tasks_with_priority,
            "done_search": done_search,
            "done_matches": done_matches
        }
    )


@app.get("/buildings/new", response_class=HTMLResponse)
def create_building_form(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="create_building.html",
        context={"user": user}
    )


@app.post("/buildings")
def create_building(
    request: Request,
    name: str = Form(...),
    address: str = Form(...),
    landlord_name: str = Form(""),
    tenant_name: str = Form(""),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)

    crud.create_building(
        db,
        name=name,
        address=address,
        landlord_name=landlord_name,
        tenant_name=tenant_name,
        user_id=user.id
    )
    return RedirectResponse(url="/", status_code=303)


@app.get("/buildings/{building_id}", response_class=HTMLResponse)
def building_detail(
    building_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    building = crud.get_building_by_id(db, building_id, user.id)

    if not building:
        raise HTTPException(status_code=404, detail="Gebäude nicht gefunden")

    open_tasks = [task for task in building.tasks if task.status == "offen"]
    done_tasks = [task for task in building.tasks if task.status == "erledigt"]

    open_tasks = sorted(
        open_tasks,
        key=lambda task: (task.due_date is None, task.due_date or date.max)
    )

    return templates.TemplateResponse(
        request=request,
        name="building_detail.html",
        context={
            "user": user,
            "building": building,
            "open_tasks": open_tasks,
            "done_tasks": done_tasks
        }
    )


@app.post("/documents/upload")
def upload_document(
    request: Request,
    building_id: int = Form(...),
    category: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    building = crud.get_building_by_id(db, building_id, user.id)

    if not building:
        raise HTTPException(status_code=404, detail="Gebäude nicht gefunden")

    stored_filename, filepath = save_upload_file(file)

    crud.create_document(
        db=db,
        original_filename=file.filename,
        stored_filename=stored_filename,
        category=category,
        filepath=filepath,
        building_id=building_id
    )

    return RedirectResponse(url=f"/buildings/{building_id}", status_code=303)


@app.post("/documents/{document_id}/delete")
def delete_document(
    request: Request,
    document_id: int,
    building_id: int = Form(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)

    document = crud.delete_document(db, document_id, user.id)

    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")

    return RedirectResponse(url=f"/buildings/{building_id}", status_code=303)


@app.get("/documents/{document_id}/download")
def download_document(
    request: Request,
    document_id: int,
    db: Session = Depends(get_db)
):
    user = require_login(request, db)

    document = crud.get_document_by_id(db, document_id, user.id)

    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")

    if not os.path.exists(document.filepath):
        raise HTTPException(status_code=404, detail="Datei nicht auf dem Server gefunden")

    return FileResponse(
        path=document.filepath,
        filename=document.original_filename,
        media_type="application/octet-stream"
    )


@app.post("/tasks")
def create_task(
    request: Request,
    building_id: int = Form(...),
    title: str = Form(...),
    note: str = Form(""),
    due_date: str = Form(""),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    building = crud.get_building_by_id(db, building_id, user.id)

    if not building:
        raise HTTPException(status_code=404, detail="Gebäude nicht gefunden")

    parsed_date = None
    if due_date:
        parsed_date = datetime.strptime(due_date, "%Y-%m-%d").date()

    crud.create_task(
        db=db,
        title=title,
        note=note,
        due_date=parsed_date,
        building_id=building_id
    )

    return RedirectResponse(url=f"/buildings/{building_id}", status_code=303)


@app.post("/tasks/{task_id}/done")
def mark_task_done(
    request: Request,
    task_id: int,
    building_id: int = Form(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)

    task = crud.mark_task_done(db, task_id, user.id)

    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

    return RedirectResponse(url=f"/buildings/{building_id}", status_code=303)


@app.post("/tasks/{task_id}/delete")
def delete_task(
    request: Request,
    task_id: int,
    building_id: int = Form(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)

    task = crud.delete_task(db, task_id, user.id)

    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

    return RedirectResponse(url=f"/buildings/{building_id}", status_code=303)