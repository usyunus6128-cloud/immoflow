import os
from datetime import datetime, date, timedelta
from typing import Any, Optional

from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, PlainTextResponse
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

VALID_ROLES = [ROLE_OWNER, ROLE_MANAGER, ROLE_EMPLOYEE, ROLE_READONLY]
VALID_USER_STATUSES = ["aktiv", "inaktiv"]

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

EMAIL_DIRECTIONS = [
    "eingehend",
    "ausgehend"
]

BUILDING_STATUSES = [
    "aktiv",
    "in Prüfung",
    "archiviert"
]

TASK_PRIORITIES = [
    "niedrig",
    "mittel",
    "hoch"
]

TASK_RECURRENCES = [
    "",
    "daily",
    "weekly",
    "monthly",
    "täglich",
    "wöchentlich",
    "monatlich",
]


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def template_exists(name: str) -> bool:
    return os.path.exists(os.path.join("app", "templates", name))


def resolve_template(*candidates: str) -> str:
    for candidate in candidates:
        if template_exists(candidate):
            return candidate
    return candidates[0]


def render_template(request: Request, template_name: str, context: dict[str, Any]):
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=context,
    )


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


def can_manage_company(user):
    return user.role == ROLE_OWNER


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


def normalize_recurrence_for_crud(value: str) -> str:
    mapping = {
        "daily": "täglich",
        "weekly": "wöchentlich",
        "monthly": "monatlich",
        "täglich": "täglich",
        "wöchentlich": "wöchentlich",
        "monatlich": "monatlich",
        "": "",
    }
    return mapping.get(value or "", "")


def validate_choice(value: str, valid_values: list[str], label: str):
    if value not in valid_values:
        raise HTTPException(status_code=400, detail=f"Ungültiger Wert für {label}")


def parse_optional_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datumsformat")


def resolve_active_company_user(db: Session, user_id_value: str, company_id: int):
    if not user_id_value:
        return None

    try:
        user_id = int(user_id_value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige Benutzer-ID")

    assigned_user = crud.get_user_by_id(db, user_id)
    if (
        not assigned_user
        or assigned_user.company_id != company_id
        or assigned_user.status != "aktiv"
    ):
        raise HTTPException(status_code=400, detail="Ungültiger Benutzer")

    return assigned_user


def build_recent_activities_for_company(db: Session, company_id: int, limit: int = 12):
    activities = []
    buildings = crud.get_all_buildings(db, company_id=company_id)

    for building in buildings:
        for document in building.documents:
            activities.append({
                "sort_date": getattr(document, "created_at", datetime.utcnow()),
                "type": "document",
                "title": "Dokument hochgeladen",
                "description": f"{document.title or document.original_filename} wurde bei {building.name} abgelegt",
                "link": f"/buildings/{building.id}?tab=documents"
            })

        for task in building.tasks:
            task_date = datetime.combine(task.due_date, datetime.min.time()) if task.due_date else datetime.utcnow()

            if task.status == "erledigt":
                activities.append({
                    "sort_date": task_date,
                    "type": "done_task",
                    "title": "Aufgabe erledigt",
                    "description": f"{task.title} bei {building.name} wurde erledigt",
                    "link": f"/buildings/{building.id}?tab=tasks"
                })
            else:
                activities.append({
                    "sort_date": task_date,
                    "type": "open_task",
                    "title": "Aufgabe offen",
                    "description": f"{task.title} bei {building.name} ist offen",
                    "link": f"/buildings/{building.id}?tab=tasks"
                })

        for email in getattr(building, "emails", []):
            activities.append({
                "sort_date": email.received_at,
                "type": "email",
                "title": "E Mail erfasst",
                "description": f"{email.subject or 'Ohne Betreff'} wurde {building.name} zugeordnet",
                "link": f"/buildings/{building.id}?tab=emails"
            })

    activities = sorted(activities, key=lambda x: x["sort_date"], reverse=True)
    return activities[:limit]


def build_timeline_for_building(building):
    timeline = []

    for document in building.documents:
        timeline.append({
            "date": getattr(document, "created_at", datetime.utcnow()),
            "type": "document",
            "title": "Dokument hochgeladen",
            "description": f"{document.title or document.original_filename} • Kategorie: {document.category}"
        })

    for task in building.tasks:
        created_like_date = datetime.combine(task.due_date, datetime.min.time()) if task.due_date else datetime.utcnow()
        if task.status == "erledigt":
            timeline.append({
                "date": created_like_date,
                "type": "done_task",
                "title": "Aufgabe erledigt",
                "description": f"{task.title} • Priorität: {task.priority}"
            })
        else:
            timeline.append({
                "date": created_like_date,
                "type": "open_task",
                "title": "Aufgabe offen",
                "description": f"{task.title} • Priorität: {task.priority}"
            })

    for email in getattr(building, "emails", []):
        timeline.append({
            "date": email.received_at,
            "type": "email",
            "title": "E Mail",
            "description": f"{email.subject or 'Ohne Betreff'} • {email.sender_name or email.sender_email or 'Unbekannter Absender'}"
        })

    for comment in [comment for task in building.tasks for comment in getattr(task, "comments", [])]:
        timeline.append({
            "date": comment.created_at,
            "type": "comment",
            "title": "Kommentar",
            "description": f"{comment.user.username}: {comment.text[:100]}"
        })

    timeline = sorted(timeline, key=lambda x: x["date"], reverse=True)
    return timeline


def get_email_thread_messages_safe(db: Session, company_id: int, email_id: int):
    if hasattr(crud, "get_email_thread_messages"):
        try:
            return crud.get_email_thread_messages(
                db=db,
                company_id=company_id,
                email_id=email_id
            )
        except Exception:
            pass

    email_message = crud.get_email_by_id(db, email_id, company_id)
    if not email_message:
        return []

    all_emails = crud.get_company_emails(db=db, company_id=company_id)
    thread_key = getattr(email_message, "thread_key", "") or str(email_message.id)

    matches = []
    for item in all_emails:
        same_thread = (getattr(item, "thread_key", "") == thread_key and thread_key)
        linked_source = getattr(item, "source_email_id", None) == email_message.id
        reverse_linked = getattr(email_message, "source_email_id", None) == item.id
        same_id = item.id == email_message.id
        if same_thread or linked_source or reverse_linked or same_id:
            matches.append(item)

    matches = sorted(matches, key=lambda x: x.received_at)
    return matches


def create_recurring_follow_up_safe(db: Session, task_id: int, company_id: int):
    if hasattr(crud, "create_next_recurring_task_if_needed"):
        return crud.create_next_recurring_task_if_needed(db, task_id, company_id)
    if hasattr(crud, "create_follow_up_recurring_task_if_needed"):
        return crud.create_follow_up_recurring_task_if_needed(db, task_id, company_id)
    if hasattr(crud, "create_follow_up_recurring_task"):
        return crud.create_follow_up_recurring_task(db, task_id, company_id)
    return None


def render_search_results_fallback(
    request: Request,
    user,
    q: str,
    buildings: list,
    emails: list,
    task_matches: list,
    document_matches: list
):
    html = [
        "<!DOCTYPE html>",
        "<html lang='de'><head><meta charset='UTF-8'><title>Suche</title>",
        "<link rel='stylesheet' href='/static/style.css'></head><body>",
        "<div class='content'>",
        f"<h1>Suche: {q}</h1>",
        "<h2>Immobilien</h2>",
    ]

    if buildings:
        html.append("<ul>")
        for building in buildings:
            html.append(f"<li><a href='/buildings/{building.id}'>{building.name} • {building.address}</a></li>")
        html.append("</ul>")
    else:
        html.append("<p>Keine Immobilien gefunden.</p>")

    html.append("<h2>Aufgaben</h2>")
    if task_matches:
        html.append("<ul>")
        for item in task_matches:
            html.append(f"<li><a href='/buildings/{item['building'].id}?tab=tasks'>{item['task'].title} • {item['building'].name}</a></li>")
        html.append("</ul>")
    else:
        html.append("<p>Keine Aufgaben gefunden.</p>")

    html.append("<h2>Dokumente</h2>")
    if document_matches:
        html.append("<ul>")
        for item in document_matches:
            html.append(f"<li><a href='/buildings/{item['building'].id}?tab=documents'>{item['document'].title or item['document'].original_filename} • {item['building'].name}</a></li>")
        html.append("</ul>")
    else:
        html.append("<p>Keine Dokumente gefunden.</p>")

    html.append("<h2>E Mails</h2>")
    if emails:
        html.append("<ul>")
        for item in emails:
            html.append(f"<li><a href='/emails/{item.id}'>{item.subject or 'Ohne Betreff'}</a></li>")
        html.append("</ul>")
    else:
        html.append("<p>Keine E Mails gefunden.</p>")

    html.append("</div></body></html>")
    return HTMLResponse("".join(html))


@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return render_template(
        request,
        resolve_template("register.html"),
        {"error": ""}
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
    company_name = company_name.strip()
    username = username.strip()
    email = email.strip()

    if not company_name or not username or not password:
        return render_template(
            request,
            resolve_template("register.html"),
            {"error": "Bitte alle Pflichtfelder ausfüllen"}
        )

    existing_company = crud.get_company_by_name(db, company_name)
    if existing_company:
        return render_template(
            request,
            resolve_template("register.html"),
            {"error": "Firmenname existiert bereits"}
        )

    company = crud.create_company(db, name=company_name)

    existing_user = crud.get_user_by_username(db, username, company.id)
    if existing_user:
        return render_template(
            request,
            resolve_template("register.html"),
            {"error": "Benutzername existiert in dieser Firma bereits"}
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
    return render_template(
        request,
        resolve_template("login.html"),
        {"error": ""}
    )


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    company_name: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    auth_result = crud.authenticate_user(db, company_name.strip(), username.strip(), password)

    if auth_result == "inactive":
        return render_template(
            request,
            resolve_template("login.html"),
            {"error": "Dieses Benutzerkonto ist inaktiv. Bitte wende dich an den Inhaber."}
        )

    if not auth_result:
        return render_template(
            request,
            resolve_template("login.html"),
            {"error": "Firmenname, Benutzername oder Passwort ist falsch"}
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
    email_counts = crud.get_email_counts_for_company(db, user.company_id)
    urgent_emails = crud.get_company_emails(
        db=db,
        company_id=user.company_id,
        status="neu"
    )[:5]

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

    for item in tasks_with_priority:
        if item["priority_text"] == "Überfällig":
            overdue_count += 1

    for building in buildings:
        total_documents += len(building.documents)

        for document in building.documents:
            recent_documents.append({
                "id": document.id,
                "title": document.title or document.original_filename,
                "subtitle": f"{building.name} • {getattr(document, 'created_at', datetime.utcnow()).strftime('%d.%m.%Y')}",
                "category": document.category,
                "link": f"/buildings/{building.id}?tab=documents"
            })

    recent_documents = sorted(recent_documents, key=lambda x: x["id"], reverse=True)[:5]
    recent_activities = build_recent_activities_for_company(db, user.company_id, limit=8)
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

    return render_template(
        request,
        resolve_template("index.html"),
        {
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
            "email_counts": email_counts,
            "urgent_emails": urgent_emails,
            "ROLE_OWNER": ROLE_OWNER,
            "ROLE_MANAGER": ROLE_MANAGER,
            "ROLE_EMPLOYEE": ROLE_EMPLOYEE,
            "ROLE_READONLY": ROLE_READONLY
        }
    )


@app.get("/search", response_class=HTMLResponse)
def global_search(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    buildings = crud.get_all_buildings(db, company_id=user.company_id, search=q) if q else []
    emails = crud.get_company_emails(db, company_id=user.company_id, search=q) if q else []

    task_matches = []
    document_matches = []

    if q:
        all_buildings = crud.get_all_buildings(db, company_id=user.company_id)
        needle = q.lower()

        for building in all_buildings:
            for task in building.tasks:
                haystack = " ".join([
                    task.title or "",
                    task.note or "",
                    task.status or "",
                    task.priority or "",
                    building.name or "",
                    building.address or ""
                ]).lower()
                if needle in haystack:
                    task_matches.append({"task": task, "building": building})

            for document in building.documents:
                haystack = " ".join([
                    document.title or "",
                    document.original_filename or "",
                    document.category or "",
                    building.name or "",
                    building.address or ""
                ]).lower()
                if needle in haystack:
                    document_matches.append({"document": document, "building": building})

    template_name = resolve_template("search_results.html")
    if template_exists(template_name):
        return render_template(
            request,
            template_name,
            {
                "user": user,
                "q": q,
                "buildings": buildings,
                "emails": emails[:20],
                "task_matches": task_matches[:20],
                "document_matches": document_matches[:20]
            }
        )

    return render_search_results_fallback(
        request=request,
        user=user,
        q=q,
        buildings=buildings,
        emails=emails[:20],
        task_matches=task_matches[:20],
        document_matches=document_matches[:20]
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

    return render_template(
        request,
        resolve_template("buildings.html"),
        {
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
                if low_priority and task.priority != "niedrig":
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

    return render_template(
        request,
        resolve_template("tasks.html"),
        {
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

    documents = sorted(documents, key=lambda item: getattr(item["document"], "created_at", datetime.utcnow()), reverse=True)

    return render_template(
        request,
        resolve_template("documents.html"),
        {
            "user": user,
            "documents": documents,
            "search": search,
            "category": category,
            "document_categories": DOCUMENT_CATEGORIES,
            "ROLE_OWNER": ROLE_OWNER,
            "ROLE_MANAGER": ROLE_MANAGER
        }
    )


@app.get("/documents/{document_id}/preview")
def preview_document(
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

    filename = (document.original_filename or "").lower()
    media_type = "application/octet-stream"

    if filename.endswith(".pdf"):
        media_type = "application/pdf"
    elif filename.endswith(".png"):
        media_type = "image/png"
    elif filename.endswith(".jpg") or filename.endswith(".jpeg"):
        media_type = "image/jpeg"

    return FileResponse(
        path=document.filepath,
        filename=document.original_filename,
        media_type=media_type
    )


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

    return render_template(
        request,
        resolve_template("edit_document.html", "edit_documents.html"),
        {
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
    validate_choice(category, DOCUMENT_CATEGORIES, "Dokumentkategorie")

    document = crud.update_document(
        db=db,
        document_id=document_id,
        company_id=user.company_id,
        title=title.strip(),
        category=category
    )

    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")

    return RedirectResponse(url="/documents", status_code=303)


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
    validate_choice(category, DOCUMENT_CATEGORIES, "Dokumentkategorie")

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

    return RedirectResponse(url=f"/buildings/{building_id}?tab=documents", status_code=303)


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

    return RedirectResponse(url=f"/buildings/{building_id}?tab=documents", status_code=303)


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

    if status:
        validate_choice(status, EMAIL_STATUSES, "E Mail Status")

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

    return render_template(
        request,
        resolve_template("emails.html"),
        {
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


@app.get("/emails/{email_id}", response_class=HTMLResponse)
def email_detail(
    email_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    email_message = crud.get_email_by_id(db, email_id, user.company_id)
    if not email_message:
        raise HTTPException(status_code=404, detail="E Mail nicht gefunden")

    thread_messages = get_email_thread_messages_safe(
        db=db,
        company_id=user.company_id,
        email_id=email_id
    )

    internal_notes = crud.get_email_internal_notes(
        db=db,
        company_id=user.company_id,
        email_id=email_id
    )

    buildings = crud.get_all_buildings(db, user.company_id)

    return render_template(
        request,
        resolve_template("email_detail.html"),
        {
            "user": user,
            "email_message": email_message,
            "thread_messages": thread_messages,
            "internal_notes": internal_notes,
            "buildings": buildings,
            "email_statuses": EMAIL_STATUSES,
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
    validate_choice(status, EMAIL_STATUSES, "E Mail Status")

    crud.create_email_message(
        db=db,
        company_id=user.company_id,
        subject=subject.strip(),
        sender_name=sender_name.strip(),
        sender_email=sender_email.strip(),
        body_text=body_text.strip(),
        direction="eingehend",
        status=status
    )

    return RedirectResponse(url="/emails", status_code=303)


@app.get("/emails/{email_id}/reply", response_class=HTMLResponse)
def reply_email_form(
    email_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    require_email_edit_role(user)

    email_message = crud.get_email_by_id(db, email_id, user.company_id)
    if not email_message:
        raise HTTPException(status_code=404, detail="E Mail nicht gefunden")

    return render_template(
        request,
        resolve_template("email_reply.html"),
        {
            "user": user,
            "email_message": email_message,
            "error": ""
        }
    )


@app.post("/emails/{email_id}/reply")
def reply_email(
    email_id: int,
    request: Request,
    reply_text: str = Form(...),
    redirect_to: str = Form("/emails"),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_email_edit_role(user)

    email_message = crud.get_email_by_id(db, email_id, user.company_id)
    if not email_message:
        raise HTTPException(status_code=404, detail="E Mail nicht gefunden")

    if not reply_text.strip():
        raise HTTPException(status_code=400, detail="Antwort darf nicht leer sein")

    if not email_message.sender_email:
        raise HTTPException(status_code=400, detail="Diese E Mail hat keine Absenderadresse")

    subject = email_message.subject or "Ohne Betreff"
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    sender_for_outgoing = getattr(user, "email", None) or user.username

    try:
        send_email_message(
            email_message.sender_email,
            subject,
            reply_text.strip()
        )
    except Exception as exc:
        return render_template(
            request,
            resolve_template("email_reply.html"),
            {
                "user": user,
                "email_message": email_message,
                "error": f"E Mail Versand fehlgeschlagen: {str(exc)}"
            }
        )

    crud.create_email_message(
        db=db,
        company_id=user.company_id,
        subject=subject,
        sender_name=user.username,
        sender_email=sender_for_outgoing,
        body_text=reply_text.strip(),
        direction="ausgehend",
        status="beantwortet",
        building_id=email_message.building_id,
        is_auto_assigned=False,
        assignment_confidence="Manuell beantwortet",
        matched_by="Antwort aus ImmoControl",
        thread_key=getattr(email_message, "thread_key", "") or str(email_message.id),
        source_email_id=email_message.id
    )

    crud.update_email_status(
        db=db,
        email_id=email_message.id,
        company_id=user.company_id,
        status="beantwortet"
    )

    return RedirectResponse(url=redirect_to, status_code=303)


@app.post("/emails/{email_id}/notes")
def add_email_internal_note(
    email_id: int,
    request: Request,
    text: str = Form(...),
    redirect_to: str = Form(""),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_email_edit_role(user)

    if not text.strip():
        raise HTTPException(status_code=400, detail="Notiz darf nicht leer sein")

    email_message = crud.get_email_by_id(db, email_id, user.company_id)
    if not email_message:
        raise HTTPException(status_code=404, detail="E Mail nicht gefunden")

    crud.create_email_internal_note(
        db=db,
        company_id=user.company_id,
        email_id=email_id,
        user_id=user.id,
        text=text.strip()
    )

    target = redirect_to or f"/emails/{email_id}"
    return RedirectResponse(url=target, status_code=303)


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

    if not email_message:
        raise HTTPException(status_code=404, detail="E Mail oder Gebäude nicht gefunden")

    return RedirectResponse(url=redirect_to, status_code=303)


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
    validate_choice(status, EMAIL_STATUSES, "E Mail Status")

    email_message = crud.update_email_status(
        db=db,
        email_id=email_id,
        company_id=user.company_id,
        status=status
    )

    if not email_message:
        raise HTTPException(status_code=404, detail="E Mail nicht gefunden")

    return RedirectResponse(url=redirect_to, status_code=303)


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

    return render_template(
        request,
        resolve_template("company.html"),
        {
            "user": user,
            "company": company,
            "company_users": users,
            "error": "",
            "success": "",
            "can_manage_company": can_manage_company(user),
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

    name = name.strip()
    existing_company = crud.get_company_by_name(db, name)
    if existing_company and existing_company.id != user.company_id:
        raise HTTPException(status_code=400, detail="Firmenname existiert bereits")

    crud.update_company(
        db=db,
        company_id=user.company_id,
        name=name,
        email=email.strip(),
        phone=phone.strip(),
        address=address.strip()
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
    validate_choice(role, VALID_ROLES, "Rolle")

    username = username.strip()
    email = email.strip()

    existing_user = crud.get_user_by_username(db, username, user.company_id)
    if existing_user:
        company = crud.get_company_by_id(db, user.company_id)
        users = crud.get_company_users(db, user.company_id)
        return render_template(
            request,
            resolve_template("company.html"),
            {
                "user": user,
                "company": company,
                "company_users": users,
                "error": "Benutzername existiert in dieser Firma bereits",
                "success": "",
                "can_manage_company": True,
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
    validate_choice(role, VALID_ROLES, "Rolle")

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
    validate_choice(status, VALID_USER_STATUSES, "Benutzerstatus")

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

    return render_template(
        request,
        resolve_template("settings.html"),
        {
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
        return render_template(
            request,
            resolve_template("settings.html"),
            {
                "user": user,
                "error": "Das aktuelle Passwort ist falsch.",
                "success": ""
            }
        )

    if len(new_password) < 6:
        return render_template(
            request,
            resolve_template("settings.html"),
            {
                "user": user,
                "error": "Das neue Passwort muss mindestens 6 Zeichen lang sein.",
                "success": ""
            }
        )

    if new_password != new_password_repeat:
        return render_template(
            request,
            resolve_template("settings.html"),
            {
                "user": user,
                "error": "Die neuen Passwörter stimmen nicht überein.",
                "success": ""
            }
        )

    crud.update_user_password(db, user.id, new_password)

    updated_user = crud.get_user_by_id(db, user.id)
    return render_template(
        request,
        resolve_template("settings.html"),
        {
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

    return render_template(
        request,
        resolve_template("create_building.html"),
        {
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
    validate_choice(status, BUILDING_STATUSES, "Gebäudestatus")

    crud.create_building(
        db=db,
        name=name.strip(),
        address=address.strip(),
        landlord_name=landlord_name.strip(),
        tenant_name=tenant_name.strip(),
        tenant_email=tenant_email.strip(),
        tenant_phone=tenant_phone.strip(),
        notes=notes.strip(),
        internal_description=internal_description.strip(),
        status=status,
        contact_person=contact_person.strip(),
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
    unassigned_emails = crud.get_unassigned_emails(db, user.company_id, limit=10)
    timeline_items = build_timeline_for_building(building)

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

    allowed_tabs = ["overview", "documents", "tasks", "emails", "timeline"]
    active_tab = tab if tab in allowed_tabs else "overview"

    return render_template(
        request,
        resolve_template("building_detail.html"),
        {
            "user": user,
            "building": building,
            "open_tasks": open_tasks,
            "done_tasks": done_tasks,
            "company_users": company_users,
            "building_emails": building_emails,
            "unassigned_emails": unassigned_emails,
            "timeline_items": timeline_items,
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

    return render_template(
        request,
        resolve_template("edit_building.html"),
        {
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
    validate_choice(status, BUILDING_STATUSES, "Gebäudestatus")

    building = crud.get_building_by_id(db, building_id, user.company_id)
    if not building:
        raise HTTPException(status_code=404, detail="Gebäude nicht gefunden")

    crud.update_building(
        db=db,
        building_id=building_id,
        company_id=user.company_id,
        name=name.strip(),
        address=address.strip(),
        landlord_name=landlord_name.strip(),
        tenant_name=tenant_name.strip(),
        tenant_email=tenant_email.strip(),
        tenant_phone=tenant_phone.strip(),
        notes=notes.strip(),
        internal_description=internal_description.strip(),
        status=status,
        contact_person=contact_person.strip()
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

    return render_template(
        request,
        resolve_template("edit_task.html", "edit_tasks.html"),
        {
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
    recurrence: str = Form(""),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)

    if user.role == ROLE_READONLY:
        raise HTTPException(status_code=403, detail="Keine Berechtigung")

    validate_choice(priority, TASK_PRIORITIES, "Aufgabenpriorität")
    if recurrence not in TASK_RECURRENCES:
        raise HTTPException(status_code=400, detail="Ungültige Wiederholung")

    task = crud.get_task_by_id(db, task_id, user.company_id)
    if not task:
        raise HTTPException(status_code=404, detail="Aufgabe nicht gefunden")

    assigned_user = resolve_active_company_user(db, assigned_user_id, user.company_id)
    assigned_user_value = assigned_user.id if assigned_user else None
    parsed_date = parse_optional_date(due_date)

    crud.update_task(
        db=db,
        task_id=task_id,
        company_id=user.company_id,
        title=title.strip(),
        note=note.strip(),
        due_date=parsed_date,
        assigned_user_id=assigned_user_value,
        priority=priority,
        recurrence=normalize_recurrence_for_crud(recurrence)
    )

    return RedirectResponse(url=f"/buildings/{task.building_id}?tab=tasks", status_code=303)


@app.post("/tasks")
def create_task(
    request: Request,
    building_id: int = Form(...),
    title: str = Form(...),
    note: str = Form(""),
    due_date: str = Form(""),
    assigned_user_id: str = Form(""),
    priority: str = Form("mittel"),
    recurrence: str = Form(""),
    db: Session = Depends(get_db)
):
    user = require_login(request, db)
    require_task_create_role(user)

    validate_choice(priority, TASK_PRIORITIES, "Aufgabenpriorität")
    if recurrence not in TASK_RECURRENCES:
        raise HTTPException(status_code=400, detail="Ungültige Wiederholung")

    building = crud.get_building_by_id(db, building_id, user.company_id)
    if not building:
        raise HTTPException(status_code=404, detail="Gebäude nicht gefunden")

    parsed_date = parse_optional_date(due_date)
    assigned_user = resolve_active_company_user(db, assigned_user_id, user.company_id)
    assigned_user_value = assigned_user.id if assigned_user else None

    crud.create_task(
        db=db,
        title=title.strip(),
        note=note.strip(),
        due_date=parsed_date,
        building_id=building_id,
        assigned_user_id=assigned_user_value,
        priority=priority,
        recurrence=normalize_recurrence_for_crud(recurrence)
    )

    return RedirectResponse(url=f"/buildings/{building_id}?tab=tasks", status_code=303)


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
    return RedirectResponse(url=f"/buildings/{task.building_id}?tab=tasks", status_code=303)


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

    if not task.assigned_user or not getattr(task.assigned_user, "email", ""):
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

    try:
        send_email_message(task.assigned_user.email, subject, body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"E Mail Versand fehlgeschlagen: {str(exc)}")

    crud.mark_task_reminder_sent(db, task_id, user.company_id)
    return RedirectResponse(url=f"/buildings/{task.building_id}?tab=tasks", status_code=303)


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

    if getattr(updated_task, "recurrence", ""):
        create_recurring_follow_up_safe(db, updated_task.id, user.company_id)

    return RedirectResponse(url=f"/buildings/{building_id}?tab=tasks", status_code=303)


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

    return RedirectResponse(url=f"/buildings/{building_id}?tab=tasks", status_code=303)


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

    return RedirectResponse(url=f"/buildings/{building_id}?tab=tasks", status_code=303)


@app.get("/system/backup-info", response_class=PlainTextResponse)
def backup_info():
    db_path = os.path.abspath("immoflow.db")
    uploads_path = os.path.abspath("uploads")

    text = (
        "Backup Hinweise für den Pilotbetrieb\n\n"
        f"Datenbank Datei:\n{db_path}\n\n"
        f"Upload Ordner:\n{uploads_path}\n\n"
        "Empfehlung:\n"
        "1. Vor Änderungen immoflow.db sichern\n"
        "2. Den kompletten uploads Ordner sichern\n"
        "3. Für ein Backup immer beide zusammen kopieren\n"
        "4. Für Wiederherstellung Datenbank Datei und uploads Ordner gemeinsam zurückspielen\n"
    )
    return PlainTextResponse(text)