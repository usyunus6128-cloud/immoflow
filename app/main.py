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

app = FastAPI(title="ImmoControl")
app.add_middleware(SessionMiddleware, secret_key="immocontrol_test_secret_key_123456")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


ROLE_OWNER = "Inhaber"
ROLE_MANAGER = "Objektmanager"
ROLE_EMPLOYEE = "Mitarbeiter"
ROLE_READONLY = "Nur Lesen"


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


def require_owner(user):
    if user.role != ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")


def require_building_creator_role(user):
    if user.role not in [ROLE_OWNER, ROLE_MANAGER]:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")


def require_task_create_role(user):
    if user.role not in [ROLE_OWNER, ROLE_MANAGER, ROLE_EMPLOYEE]:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")


def require_document_upload_role(user):
    if user.role not in [ROLE_OWNER, ROLE_MANAGER, ROLE_EMPLOYEE]:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")


def require_document_delete_role(user):
    if user.role not in [ROLE_OWNER, ROLE_MANAGER]:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")


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
    company_name: str = Form(...),
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

    existing_company = crud.get_company_by_name(db, company_name)
    if existing_company:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Firmenname existiert bereits"}
        )

    company = crud.create_company(db, name=company_name)
    user = crud.create_user(
        db,
        username=username,
        password=password,
        company_id=company.id,
        role=ROLE_OWNER
    )

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

    buildings = crud.get_all_buildings(db, company_id=user.company_id, search=search)
    open_tasks = crud.get_open_tasks_sorted(db, company_id=user.company_id)

    tasks_with_priority = []
    for task in open_tasks:
        priority_text, priority_class = get_task_priority(task)
        tasks_with_priority.append({
            "task": task,
            "priority_text": priority_text,
            "priority_class": priority_class,
            "is_mine": task.assigned_user_id == user.id if task.assigned_user_id else False
        })

    done_buildings = crud.get_all_buildings(db, company_id=user.company_id, search=done_search)
    done_matches = []

    for building in done_buildings:
        done_tasks = [task for task in building.tasks if task.status == "erledigt"]
        if done_tasks:
            done_matches.append({
                "building": building,
                "tasks": done_tasks
            })

    total_documents = 0
    overdue_count = 0
    recent_documents = []
    recent_activities = []

    for item in tasks_with_priority:
        if item["priority_text"] == "Überfällig":
            overdue_count += 1

    for building in buildings:
        total_documents += len(building.documents)

        for document in building.documents:
            recent_documents.append({
                "id": document.id,
                "title": document.original_filename,
                "subtitle": f"Dokument zu {building.name} hochgeladen",
                "category": document.category,
                "link": f"/buildings/{building.id}"
            })

            recent_activities.append({
                "sort_id": document.id,
                "type": "document",
                "title": "Dokument hochgeladen",
                "description": f"{document.original_filename} wurde bei {building.name} abgelegt",
                "link": f"/buildings/{building.id}"
            })

        for task in building.tasks:
            if task.status == "erledigt":
                recent_activities.append({
                    "sort_id": task.id,
                    "type": "done_task",
                    "title": "Aufgabe erledigt",
                    "description": f"{task.title} bei {building.name} wurde erledigt",
                    "link": f"/buildings/{building.id}"
                })
            else:
                recent_activities.append({
                    "sort_id": task.id,
                    "type": "open_task",
                    "title": "Aufgabe erstellt",
                    "description": f"{task.title} bei {building.name} ist offen",
                    "link": f"/buildings/{building.id}"
                })

    recent_documents = sorted(recent_documents, key=lambda x: x["id"], reverse=True)[:5]
    recent_activities = sorted(recent_activities, key=lambda x: x["sort_id"], reverse=True)[:6]

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "buildings": buildings,
            "search": search,
            "tasks_with_priority": tasks_with_priority,
            "done_search": done_search,
            "done_matches": done_matches,
            "total_documents": total_documents,
            "overdue_count": overdue_count,
            "recent_documents": recent_documents,
            "recent_activities": recent_activities,
            "ROLE_OWNER": ROLE_OWNER,
            "ROLE_MANAGER": ROLE_MANAGER,
            "ROLE_EMPLOYEE": ROLE_EMPLOYEE,
            "ROLE_READONLY": ROLE_READONLY
        }
    )


@app.get("/buildings", response_class=HTMLResponse)
def buildings_page(
    request: Request,
    search: str = "",
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    buildings = crud.get_all_buildings(db, company_id=user.company_id, search=search)

    return templates.TemplateResponse(
        request=request,
        name="buildings.html",
        context={
            "user": user,
            "buildings": buildings,
            "search": search,
            "ROLE_OWNER": ROLE_OWNER,
            "ROLE_MANAGER": ROLE_MANAGER
        }
    )


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    buildings = crud.get_all_buildings(db, company_id=user.company_id)

    open_tasks_with_priority = []
    done_tasks_list = []

    for building in buildings:
        for task in building.tasks:
            if task.status == "offen":
                priority_text, priority_class = get_task_priority(task)
                open_tasks_with_priority.append({
                    "task": task,
                    "building": building,
                    "priority_text": priority_text,
                    "priority_class": priority_class,
                    "is_mine": task.assigned_user_id == user.id if task.assigned_user_id else False
                })
            elif task.status == "erledigt":
                done_tasks_list.append({
                    "task": task,
                    "building": building,
                    "is_mine": task.assigned_user_id == user.id if task.assigned_user_id else False
                })

    open_tasks_with_priority = sorted(
        open_tasks_with_priority,
        key=lambda item: (
            0 if item["is_mine"] else 1,
            item["task"].due_date is None,
            item["task"].due_date or date.max
        )
    )

    done_tasks_list = sorted(
        done_tasks_list,
        key=lambda item: item["task"].id,
        reverse=True
    )

    return templates.TemplateResponse(
        request=request,
        name="tasks.html",
        context={
            "user": user,
            "open_tasks_with_priority": open_tasks_with_priority,
            "done_tasks_list": done_tasks_list
        }
    )


@app.get("/documents", response_class=HTMLResponse)
def documents_page(
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    buildings = crud.get_all_buildings(db, company_id=user.company_id)
    documents = []

    for building in buildings:
        for document in building.documents:
            documents.append({
                "document": document,
                "building": building
            })

    documents = sorted(documents, key=lambda item: item["document"].id, reverse=True)

    return templates.TemplateResponse(
        request=request,
        name="documents.html",
        context={
            "user": user,
            "documents": documents
        }
    )


@app.get("/company", response_class=HTMLResponse)
def company_page(
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    company = crud.get_company_by_id(db, user.company_id)
    users = crud.get_company_users(db, user.company_id)

    return templates.TemplateResponse(
        request=request,
        name="company.html",
        context={
            "user": user,
            "company": company,
            "company_users": users,
            "error": "",
            "success": "",
            "ROLE_OWNER": ROLE_OWNER,
            "ROLE_MANAGER": ROLE_MANAGER,
            "ROLE_EMPLOYEE": ROLE_EMPLOYEE,
            "ROLE_READONLY": ROLE_READONLY
        }
    )


@app.post("/company")
def update_company(
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_owner(user)

    existing_company = crud.get_company_by_name(db, name)
    if existing_company and existing_company.id != user.company_id:
        raise HTTPException(status_code=400, detail="Firmenname existiert bereits")

    crud.update_company(
        db=db,
        company_id=user.company_id,
        name=name,
        email=email,
        phone=phone,
        address=address
    )

    return RedirectResponse(url="/company", status_code=303)


@app.post("/company/users")
def create_company_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_owner(user)

    existing_user = crud.get_user_by_username(db, username)
    if existing_user:
        company = crud.get_company_by_id(db, user.company_id)
        users = crud.get_company_users(db, user.company_id)
        return templates.TemplateResponse(
            request=request,
            name="company.html",
            context={
                "user": user,
                "company": company,
                "company_users": users,
                "error": "Benutzername existiert bereits",
                "success": "",
                "ROLE_OWNER": ROLE_OWNER,
                "ROLE_MANAGER": ROLE_MANAGER,
                "ROLE_EMPLOYEE": ROLE_EMPLOYEE,
                "ROLE_READONLY": ROLE_READONLY
            }
        )

    crud.create_user(
        db=db,
        username=username,
        password=password,
        company_id=user.company_id,
        role=role
    )

    return RedirectResponse(url="/company", status_code=303)


@app.post("/company/users/{target_user_id}/role")
def update_company_user_role(
    request: Request,
    target_user_id: int,
    role: str = Form(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_owner(user)

    target_user = crud.get_user_by_id(db, target_user_id)
    if not target_user or target_user.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    if target_user.id == user.id and role != ROLE_OWNER:
        raise HTTPException(status_code=400, detail="Der Inhaber kann sich nicht selbst herabstufen")

    crud.update_user_role(
        db=db,
        user_id=target_user_id,
        company_id=user.company_id,
        new_role=role
    )

    return RedirectResponse(url="/company", status_code=303)


@app.get("/buildings/new", response_class=HTMLResponse)
def create_building_form(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if user.role not in [ROLE_OWNER, ROLE_MANAGER]:
        return RedirectResponse(url="/", status_code=303)

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
    tenant_email: str = Form(""),
    tenant_phone: str = Form(""),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_building_creator_role(user)

    crud.create_building(
        db,
        name=name,
        address=address,
        landlord_name=landlord_name,
        tenant_name=tenant_name,
        tenant_email=tenant_email,
        tenant_phone=tenant_phone,
        company_id=user.company_id,
        created_by_user_id=user.id
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

    building = crud.get_building_by_id(db, building_id, user.company_id)

    if not building:
        raise HTTPException(status_code=404, detail="Gebäude nicht gefunden")

    open_tasks = [task for task in building.tasks if task.status == "offen"]
    done_tasks = [task for task in building.tasks if task.status == "erledigt"]
    company_users = crud.get_company_users(db, user.company_id)

    open_tasks = sorted(
        open_tasks,
        key=lambda task: (
            0 if task.assigned_user_id == user.id else 1,
            task.due_date is None,
            task.due_date or date.max
        )
    )

    return templates.TemplateResponse(
        request=request,
        name="building_detail.html",
        context={
            "user": user,
            "building": building,
            "open_tasks": open_tasks,
            "done_tasks": done_tasks,
            "company_users": company_users,
            "ROLE_OWNER": ROLE_OWNER,
            "ROLE_MANAGER": ROLE_MANAGER,
            "ROLE_EMPLOYEE": ROLE_EMPLOYEE,
            "ROLE_READONLY": ROLE_READONLY
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
    require_document_upload_role(user)

    building = crud.get_building_by_id(db, building_id, user.company_id)

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
    require_document_delete_role(user)

    document = crud.delete_document(db, document_id, user.company_id)

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

    document = crud.get_document_by_id(db, document_id, user.company_id)

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
    assigned_user_id: str = Form(""),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_task_create_role(user)

    building = crud.get_building_by_id(db, building_id, user.company_id)

    if not building:
        raise HTTPException(status_code=404, detail="Gebäude nicht gefunden")

    parsed_date = None
    if due_date:
        parsed_date = datetime.strptime(due_date, "%Y-%m-%d").date()

    assigned_user_value = None
    if assigned_user_id:
        assigned_user_value = int(assigned_user_id)
        assigned_user = crud.get_user_by_id(db, assigned_user_value)
        if not assigned_user or assigned_user.company_id != user.company_id:
            raise HTTPException(status_code=400, detail="Ungültiger Benutzer")

    crud.create_task(
        db=db,
        title=title,
        note=note,
        due_date=parsed_date,
        building_id=building_id,
        assigned_user_id=assigned_user_value
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

    task = crud.get_task_by_id(db, task_id, user.company_id)
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

    if user.role == ROLE_READONLY:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    if user.role == ROLE_EMPLOYEE and task.assigned_user_id and task.assigned_user_id != user.id:
        raise HTTPException(status_code=403, detail="Du darfst nur eigene zugewiesene Aufgaben erledigen")

    updated_task = crud.mark_task_done(db, task_id, user.company_id)
    if not updated_task:
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

    task = crud.get_task_by_id(db, task_id, user.company_id)
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

    if user.role not in [ROLE_OWNER, ROLE_MANAGER]:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    deleted_task = crud.delete_task(db, task_id, user.company_id)
    if not deleted_task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

    return RedirectResponse(url=f"/buildings/{building_id}", status_code=303)