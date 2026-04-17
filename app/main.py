import os
from datetime import datetime, date, timedelta

from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app import crud
from app.utils import save_upload_file, ensure_upload_dir, send_email_message

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

DOCUMENT_CATEGORIES = [
    "Rechnung",
    "Vertrag",
    "Nebenkosten",
    "Versicherung",
    "Steuer",
    "Wartung",
    "Schriftverkehr",
    "Sonstiges"
]

EMAIL_STATUSES = [
    "neu",
    "offen",
    "bearbeitet",
    "beantwortet",
    "archiviert"
]

BUILDING_STATUSES = [
    "aktiv",
    "in Prüfung",
    "archiviert"
]

TASK_PRIORITIES = [
    "status",
    "mittel",
    "hoch"
]

EMAIL_STATUSES = [
    "neu",
    "offen",
    "bearbeitet",
    "beantwortet",
    "archiviert"
]

EMAIL_DIRECTIONS = [
    "eingehend",
    "ausgehend"
]


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


def require_email_edit_role(user):
    if user.role == ROLE_READONLY:
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
    email: str = Form(""),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    existing_company = crud.get_company_by_name(db, company_name)
    if existing_company:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Firmenname existiert bereits"}
        )

    company = crud.create_company(db, name=company_name)

    existing_user = crud.get_user_by_username(db, username, company.id)
    if existing_user:
        return templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"error": "Benutzername existiert in dieser Firma bereits"}
        )

    user = crud.create_user(
        db=db,
        username=username,
        email=email,
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
    company_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    auth_result = crud.authenticate_user(db, company_name, username, password)

    if auth_result == "inactive":
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Dieses Benutzerkonto ist inaktiv. Bitte wende dich an den Inhaber."}
        )

    if not auth_result:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Firmenname, Benutzername oder Passwort ist falsch"}
        )

    request.session["user_id"] = auth_result.id
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
    my_tasks = []

    for task in open_tasks:
        priority_text, priority_class = get_task_priority(task)
        item = {
            "task": task,
            "priority_text": priority_text,
            "priority_class": priority_class,
            "is_mine": task.assigned_user_id == user.id if task.assigned_user_id else False
        }
        tasks_with_priority.append(item)

        if item["is_mine"]:
            my_tasks.append(item)

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
                "title": document.title or document.original_filename,
                "subtitle": f"{building.name} • {document.created_at.strftime('%d.%m.%Y')}",
                "category": document.category,
                "link": f"/buildings/{building.id}"
            })

            recent_activities.append({
                "sort_id": document.id,
                "type": "document",
                "title": "Dokument hochgeladen",
                "description": f"{document.title or document.original_filename} wurde bei {building.name} abgelegt",
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
    recent_comments = crud.get_recent_comments_for_company(db, user.company_id, limit=5)
    today_tasks_count = crud.get_today_tasks_count(db, user.company_id)
    week_tasks_count = crud.get_week_tasks_count(db, user.company_id)

    my_tasks = sorted(
        my_tasks,
        key=lambda item: (
            item["task"].due_date is None,
            item["task"].due_date or date.max
        )
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "buildings": buildings,
            "search": search,
            "tasks_with_priority": tasks_with_priority,
            "my_tasks": my_tasks,
            "done_search": done_search,
            "done_matches": done_matches,
            "total_documents": total_documents,
            "overdue_count": overdue_count,
            "today_tasks_count": today_tasks_count,
            "week_tasks_count": week_tasks_count,
            "recent_documents": recent_documents,
            "recent_activities": recent_activities,
            "recent_comments": recent_comments,
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
    mine: str = "",
    open_only: str = "",
    done_only: str = "",
    overdue: str = "",
    due_today: str = "",
    due_week: str = "",
    high_priority: str = "",
    medium_priority: str = "",
    low_priority: str = "",
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    buildings = crud.get_all_buildings(db, company_id=user.company_id)
    today = date.today()
    week_end = today + timedelta(days=7)

    open_tasks_with_priority = []
    done_tasks_list = []

    for building in buildings:
        for task in building.tasks:
            is_mine = task.assigned_user_id == user.id if task.assigned_user_id else False
            priority_text, priority_class = get_task_priority(task)

            if task.status == "offen":
                item = {
                    "task": task,
                    "building": building,
                    "priority_text": priority_text,
                    "priority_class": priority_class,
                    "is_mine": is_mine
                }

                if mine and not is_mine:
                    continue
                if overdue and not (task.due_date and task.due_date < today):
                    continue
                if due_today and not (task.due_date == today):
                    continue
                if due_week and not (task.due_date and today <= task.due_date <= week_end):
                    continue
                if high_priority and task.priority != "hoch":
                    continue
                if medium_priority and task.priority != "mittel":
                    continue
                if low_priority and task.priority != "status":
                    continue
                if done_only:
                    continue

                open_tasks_with_priority.append(item)

            elif task.status == "erledigt":
                item = {
                    "task": task,
                    "building": building,
                    "is_mine": is_mine
                }

                if mine and not is_mine:
                    continue
                if open_only:
                    continue
                if overdue or due_today or due_week or high_priority or medium_priority or low_priority:
                    continue

                done_tasks_list.append(item)

    if not done_only:
        open_tasks_with_priority = sorted(
            open_tasks_with_priority,
            key=lambda item: (
                0 if item["priority_text"] == "Überfällig" else 1,
                0 if item["is_mine"] else 1,
                0 if item["task"].priority == "hoch" else 1 if item["task"].priority == "mittel" else 2,
                item["task"].due_date is None,
                item["task"].due_date or date.max
            )
        )
    else:
        open_tasks_with_priority = []

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
            "done_tasks_list": done_tasks_list,
            "mine": mine,
            "open_only": open_only,
            "done_only": done_only,
            "overdue": overdue,
            "due_today": due_today,
            "due_week": due_week,
            "high_priority": high_priority,
            "medium_priority": medium_priority,
            "low_priority": low_priority
        }
    )


@app.get("/documents", response_class=HTMLResponse)
def documents_page(
    request: Request,
    search: str = "",
    category: str = "",
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    buildings = crud.get_all_buildings(db, company_id=user.company_id)
    documents = []

    for building in buildings:
        for document in building.documents:
            matches_search = True
            matches_category = True

            if search:
                search_value = search.lower()
                matches_search = (
                    search_value in (document.original_filename or "").lower()
                    or search_value in (document.title or "").lower()
                    or search_value in (document.category or "").lower()
                    or search_value in (building.name or "").lower()
                    or search_value in (building.address or "").lower()
                )

            if category:
                matches_category = document.category == category

            if matches_search and matches_category:
                documents.append({
                    "document": document,
                    "building": building
                })

    documents = sorted(documents, key=lambda item: item["document"].created_at, reverse=True)

    return templates.TemplateResponse(
        request=request,
        name="documents.html",
        context={
            "user": user,
            "documents": documents,
            "search": search,
            "category": category,
            "document_categories": DOCUMENT_CATEGORIES,
            "ROLE_OWNER": ROLE_OWNER,
            "ROLE_MANAGER": ROLE_MANAGER
        }
    )


@app.get("/emails", response_class=HTMLResponse)
def emails_page(
    request: Request,
    search: str = "",
    status: str = "",
    mode: str = "",
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    only_unassigned = mode == "unassigned"
    only_assigned = mode == "assigned"

    emails = crud.get_company_emails(
        db=db,
        company_id=user.company_id,
        search=search,
        status=status,
        only_unassigned=only_unassigned,
        only_assigned=only_assigned
    )

    buildings = crud.get_all_buildings(db, user.company_id)
    email_counts = crud.get_email_counts_for_company(db, user.company_id)

    return templates.TemplateResponse(
        request=request,
        name="emails.html",
        context={
            "user": user,
            "emails": emails,
            "search": search,
            "status": status,
            "mode": mode,
            "buildings": buildings,
            "email_statuses": EMAIL_STATUSES,
            "email_counts": email_counts,
            "ROLE_OWNER": ROLE_OWNER,
            "ROLE_MANAGER": ROLE_MANAGER,
            "ROLE_EMPLOYEE": ROLE_EMPLOYEE,
            "ROLE_READONLY": ROLE_READONLY
        }
    )


@app.post("/emails/manual")
def create_manual_email(
    request: Request,
    sender_name: str = Form(""),
    sender_email: str = Form(""),
    subject: str = Form(""),
    body_text: str = Form(""),
    status: str = Form("neu"),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_email_edit_role(user)

    crud.create_email_message(
        db=db,
        company_id=user.company_id,
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email,
        body_text=body_text,
        direction="eingehend",
        status=status
    )

    return RedirectResponse(url="/emails", status_code=303)


@app.post("/emails/{email_id}/assign")
def assign_email(
    email_id: int,
    request: Request,
    building_id: int = Form(...),
    redirect_to: str = Form("/emails"),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_email_edit_role(user)

    email_message = crud.assign_email_to_building(
        db=db,
        email_id=email_id,
        company_id=user.company_id,
        building_id=building_id
    )

@app.post("/emails/{email_id}/assign")
def assign_email(
    request: Request,
    email_id: int,
    building_id: int = Form(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)

    crud.assign_email_to_building(db, email_id, building_id, user.company_id)

    return RedirectResponse(url="/emails", status_code=303)


    if not email_message:
        raise HTTPException(status_code=404, detail="E Mail oder Gebäude nicht gefunden")

    return RedirectResponse(url=redirect_to, status_code=303)


@app.get("/emails/test")
def create_test_email(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)

    crud.create_email(
        db,
        subject="Dusche kaputt",
        sender_name="Max Mustermann",
        sender_email="max@gmail.com",
        body="Hallo, meine Dusche ist kaputt",
        company_id=user.company_id
    )

    return RedirectResponse(url="/emails", status_code=303)


@app.post("/emails/{email_id}/unassign")
def unassign_email(
    email_id: int,
    request: Request,
    redirect_to: str = Form("/emails"),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_email_edit_role(user)

    email_message = crud.unassign_email_from_building(
        db=db,
        email_id=email_id,
        company_id=user.company_id
    )

    if not email_message:
        raise HTTPException(status_code=404, detail="E Mail nicht gefunden")

    return RedirectResponse(url=redirect_to, status_code=303)


@app.post("/emails/{email_id}/status")
def update_email_status(
    email_id: int,
    request: Request,
    status: str = Form(...),
    redirect_to: str = Form("/emails"),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_email_edit_role(user)

    email_message = crud.update_email_status(
        db=db,
        email_id=email_id,
        company_id=user.company_id,
        status=status
    )

    if not email_message:
        raise HTTPException(status_code=404, detail="E Mail nicht gefunden")

    return RedirectResponse(url=redirect_to, status_code=303)


@app.get("/documents/{document_id}/edit", response_class=HTMLResponse)
def edit_document_form(
    document_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if user.role not in [ROLE_OWNER, ROLE_MANAGER]:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    document = crud.get_document_by_id(db, document_id, user.company_id)
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")

    return templates.TemplateResponse(
        request=request,
        name="edit_document.html",
        context={
            "user": user,
            "document": document,
            "document_categories": DOCUMENT_CATEGORIES
        }
    )


@app.post("/documents/{document_id}/edit")
def edit_document(
    document_id: int,
    request: Request,
    title: str = Form(""),
    category: str = Form(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_document_delete_role(user)

    document = crud.update_document(
        db=db,
        document_id=document_id,
        company_id=user.company_id,
        title=title,
        category=category
    )

    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")

    return RedirectResponse(url="/documents", status_code=303)


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
    email: str = Form(""),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_owner(user)

    existing_user = crud.get_user_by_username(db, username, user.company_id)
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
                "error": "Benutzername existiert in dieser Firma bereits",
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
        email=email,
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


@app.post("/company/users/{target_user_id}/status")
def update_company_user_status(
    request: Request,
    target_user_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_owner(user)

    target_user = crud.get_user_by_id(db, target_user_id)
    if not target_user or target_user.company_id != user.company_id:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    if target_user.id == user.id and status != "aktiv":
        raise HTTPException(status_code=400, detail="Der Inhaber kann sich nicht selbst deaktivieren")

    crud.update_user_status(
        db=db,
        user_id=target_user_id,
        company_id=user.company_id,
        new_status=status
    )

    return RedirectResponse(url="/company", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "user": user,
            "error": "",
            "success": ""
        }
    )


@app.post("/settings/password", response_class=HTMLResponse)
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password_repeat: str = Form(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)

    if not crud.verify_password(current_password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="settings.html",
            context={
                "user": user,
                "error": "Das aktuelle Passwort ist falsch.",
                "success": ""
            }
        )

    if len(new_password) < 6:
        return templates.TemplateResponse(
            request=request,
            name="settings.html",
            context={
                "user": user,
                "error": "Das neue Passwort muss mindestens 6 Zeichen lang sein.",
                "success": ""
            }
        )

    if new_password != new_password_repeat:
        return templates.TemplateResponse(
            request=request,
            name="settings.html",
            context={
                "user": user,
                "error": "Die neuen Passwörter stimmen nicht überein.",
                "success": ""
            }
        )

    crud.update_user_password(db, user.id, new_password)

    updated_user = crud.get_user_by_id(db, user.id)
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "user": updated_user,
            "error": "",
            "success": "Passwort erfolgreich geändert."
        }
    )


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
        context={
            "user": user,
            "building_statuses": BUILDING_STATUSES
        }
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
    notes: str = Form(""),
    internal_description: str = Form(""),
    status: str = Form("aktiv"),
    contact_person: str = Form(""),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_building_creator_role(user)

    crud.create_building(
        db=db,
        name=name,
        address=address,
        landlord_name=landlord_name,
        tenant_name=tenant_name,
        tenant_email=tenant_email,
        tenant_phone=tenant_phone,
        notes=notes,
        internal_description=internal_description,
        status=status,
        contact_person=contact_person,
        company_id=user.company_id,
        created_by_user_id=user.id
    )
    return RedirectResponse(url="/", status_code=303)


@app.get("/buildings/{building_id}", response_class=HTMLResponse)
def building_detail(
    building_id: int,
    request: Request,
    tab: str = "overview",
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
    company_users = crud.get_active_company_users(db, user.company_id)
    building_emails = crud.get_building_emails(db, building.id, user.company_id)

    open_tasks = sorted(
        open_tasks,
        key=lambda task: (
            0 if task.due_date and task.due_date < date.today() else 1,
            0 if task.priority == "hoch" else 1 if task.priority == "mittel" else 2,
            0 if task.assigned_user_id == user.id else 1,
            task.due_date is None,
            task.due_date or date.max
        )
    )

    allowed_tabs = ["overview", "documents", "tasks", "emails"]
    active_tab = tab if tab in allowed_tabs else "overview"

    return templates.TemplateResponse(
        request=request,
        name="building_detail.html",
        context={
            "user": user,
            "building": building,
            "open_tasks": open_tasks,
            "done_tasks": done_tasks,
            "company_users": company_users,
            "building_emails": building_emails,
            "active_tab": active_tab,
            "email_statuses": EMAIL_STATUSES,
            "ROLE_OWNER": ROLE_OWNER,
            "ROLE_MANAGER": ROLE_MANAGER,
            "ROLE_EMPLOYEE": ROLE_EMPLOYEE,
            "ROLE_READONLY": ROLE_READONLY,
            "current_date": date.today(),
            "document_categories": DOCUMENT_CATEGORIES,
            "task_priorities": TASK_PRIORITIES
        }
    )


@app.get("/buildings/{building_id}/edit", response_class=HTMLResponse)
def edit_building_form(
    building_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if user.role not in [ROLE_OWNER, ROLE_MANAGER]:
        return RedirectResponse(url=f"/buildings/{building_id}", status_code=303)

    building = crud.get_building_by_id(db, building_id, user.company_id)
    if not building:
        raise HTTPException(status_code=404, detail="Gebäude nicht gefunden")

    return templates.TemplateResponse(
        request=request,
        name="edit_building.html",
        context={
            "user": user,
            "building": building,
            "building_statuses": BUILDING_STATUSES
        }
    )


@app.post("/buildings/{building_id}/edit")
def edit_building(
    building_id: int,
    request: Request,
    name: str = Form(...),
    address: str = Form(...),
    landlord_name: str = Form(""),
    tenant_name: str = Form(""),
    tenant_email: str = Form(""),
    tenant_phone: str = Form(""),
    notes: str = Form(""),
    internal_description: str = Form(""),
    status: str = Form("aktiv"),
    contact_person: str = Form(""),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_building_creator_role(user)

    building = crud.get_building_by_id(db, building_id, user.company_id)
    if not building:
        raise HTTPException(status_code=404, detail="Gebäude nicht gefunden")

    crud.update_building(
        db=db,
        building_id=building_id,
        company_id=user.company_id,
        name=name,
        address=address,
        landlord_name=landlord_name,
        tenant_name=tenant_name,
        tenant_email=tenant_email,
        tenant_phone=tenant_phone,
        notes=notes,
        internal_description=internal_description,
        status=status,
        contact_person=contact_person
    )

    return RedirectResponse(url=f"/buildings/{building_id}", status_code=303)


@app.post("/buildings/{building_id}/delete")
def delete_building(
    building_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_building_creator_role(user)

    building = crud.delete_building(db, building_id, user.company_id)
    if not building:
        raise HTTPException(status_code=404, detail="Gebäude nicht gefunden")

    return RedirectResponse(url="/buildings", status_code=303)


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
        title=file.filename,
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


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_task_form(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    task = crud.get_task_by_id(db, task_id, user.company_id)
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

    if user.role == ROLE_READONLY:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    company_users = crud.get_active_company_users(db, user.company_id)

    return templates.TemplateResponse(
        request=request,
        name="edit_task.html",
        context={
            "user": user,
            "task": task,
            "company_users": company_users,
            "task_priorities": TASK_PRIORITIES,
            "ROLE_READONLY": ROLE_READONLY
        }
    )


@app.post("/tasks/{task_id}/edit")
def edit_task(
    task_id: int,
    request: Request,
    title: str = Form(...),
    note: str = Form(""),
    due_date: str = Form(""),
    assigned_user_id: str = Form(""),
    priority: str = Form("mittel"),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)

    if user.role == ROLE_READONLY:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    task = crud.get_task_by_id(db, task_id, user.company_id)
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

    parsed_date = None
    if due_date:
        parsed_date = datetime.strptime(due_date, "%Y-%m-%d").date()

    assigned_user_value = None
    if assigned_user_id:
        assigned_user_value = int(assigned_user_id)
        assigned_user = crud.get_user_by_id(db, assigned_user_value)
        if (
            not assigned_user
            or assigned_user.company_id != user.company_id
            or assigned_user.status != "aktiv"
        ):
            raise HTTPException(status_code=400, detail="Ungültiger Benutzer")

    crud.update_task(
        db=db,
        task_id=task_id,
        company_id=user.company_id,
        title=title,
        note=note,
        due_date=parsed_date,
        assigned_user_id=assigned_user_value,
        priority=priority
    )

    return RedirectResponse(url=f"/buildings/{task.building_id}", status_code=303)


@app.post("/tasks")
def create_task(
    request: Request,
    building_id: int = Form(...),
    title: str = Form(...),
    note: str = Form(""),
    due_date: str = Form(""),
    assigned_user_id: str = Form(""),
    priority: str = Form("mittel"),
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
        if (
            not assigned_user
            or assigned_user.company_id != user.company_id
            or assigned_user.status != "aktiv"
        ):
            raise HTTPException(status_code=400, detail="Ungültiger Benutzer")

    crud.create_task(
        db=db,
        title=title,
        note=note,
        due_date=parsed_date,
        building_id=building_id,
        assigned_user_id=assigned_user_value,
        priority=priority
    )

    return RedirectResponse(url=f"/buildings/{building_id}", status_code=303)


@app.post("/tasks/{task_id}/comment")
def add_task_comment(
    request: Request,
    task_id: int,
    text: str = Form(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)

    task = crud.get_task_by_id(db, task_id, user.company_id)
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

    if user.role == ROLE_READONLY:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    if not text.strip():
        raise HTTPException(status_code=400, detail="Kommentar darf nicht leer sein")

    crud.create_task_comment(db, task_id, user.id, text.strip())

    return RedirectResponse(url=f"/buildings/{task.building_id}", status_code=303)


@app.post("/tasks/{task_id}/send-reminder")
def send_task_reminder(
    request: Request,
    task_id: int,
    db: Session = Depends(get_db)
):
    user = require_login(request, db)

    if user.role not in [ROLE_OWNER, ROLE_MANAGER]:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    task = crud.get_task_by_id(db, task_id, user.company_id)
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

    if not task.assigned_user or not task.assigned_user.email:
        raise HTTPException(status_code=400, detail="Dem zugewiesenen Benutzer fehlt eine E Mail Adresse")

    subject = f"Erinnerung: {task.title}"
    body = (
        f"Hallo {task.assigned_user.username},\n\n"
        f"dies ist eine Erinnerung zur Aufgabe:\n"
        f"{task.title}\n\n"
        f"Objekt: {task.building.name}\n"
        f"Adresse: {task.building.address}\n"
        f"Fälligkeitsdatum: {task.due_date if task.due_date else 'Kein Datum'}\n"
        f"Priorität: {task.priority}\n\n"
        f"Notiz:\n{task.note or 'Keine Notiz'}\n"
    )

    send_email_message(task.assigned_user.email, subject, body)
    crud.mark_task_reminder_sent(db, task_id, user.company_id)

    return RedirectResponse(url=f"/buildings/{task.building_id}", status_code=303)


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


@app.post("/tasks/{task_id}/reopen")
def reopen_task(
    request: Request,
    task_id: int,
    building_id: int = Form(...),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)

    if user.role == ROLE_READONLY:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    task = crud.mark_task_open(db, task_id, user.company_id)
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

    task = crud.get_task_by_id(db, task_id, user.company_id)
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

    if user.role not in [ROLE_OWNER, ROLE_MANAGER]:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    deleted_task = crud.delete_task(db, task_id, user.company_id)
    if not deleted_task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

    return RedirectResponse(url=f"/buildings/{building_id}", status_code=303)