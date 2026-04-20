import os
import re
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from passlib.context import CryptContext

from app import models

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str):
    return pwd_context.verify(password, password_hash)


def get_company_by_name(db: Session, company_name: str):
    return (
        db.query(models.Company)
        .filter(models.Company.name == company_name)
        .first()
    )


def get_company_by_id(db: Session, company_id: int):
    return (
        db.query(models.Company)
        .filter(models.Company.id == company_id)
        .first()
    )


def create_company(
    db: Session,
    name: str,
    email: str = "",
    phone: str = "",
    address: str = ""
):
    company = models.Company(
        name=name,
        email=email,
        phone=phone,
        address=address
    )
    db.add(company)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(company)
    return company


def update_company(
    db: Session,
    company_id: int,
    name: str,
    email: str,
    phone: str,
    address: str
):
    company = get_company_by_id(db, company_id)
    if not company:
        return None

    company.name = name
    company.email = email
    company.phone = phone
    company.address = address

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None

    db.refresh(company)
    return company


def get_user_by_username(db: Session, username: str, company_id: int):
    return (
        db.query(models.User)
        .filter(
            models.User.username == username,
            models.User.company_id == company_id
        )
        .first()
    )


def get_user_by_id(db: Session, user_id: int):
    return (
        db.query(models.User)
        .options(joinedload(models.User.company))
        .filter(models.User.id == user_id)
        .first()
    )


def get_company_users(db: Session, company_id: int):
    return (
        db.query(models.User)
        .filter(models.User.company_id == company_id)
        .order_by(models.User.id.desc())
        .all()
    )


def get_active_company_users(db: Session, company_id: int):
    return (
        db.query(models.User)
        .filter(
            models.User.company_id == company_id,
            models.User.status == "aktiv"
        )
        .order_by(models.User.username.asc())
        .all()
    )


def create_user(
    db: Session,
    username: str,
    email: str,
    password: str,
    company_id: int,
    role: str = "Mitarbeiter"
):
    user = models.User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        company_id=company_id,
        role=role,
        status="aktiv"
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(user)
    return user


def update_user_role(db: Session, user_id: int, company_id: int, new_role: str):
    user = (
        db.query(models.User)
        .filter(
            models.User.id == user_id,
            models.User.company_id == company_id
        )
        .first()
    )
    if not user:
        return None

    user.role = new_role
    db.commit()
    db.refresh(user)
    return user


def update_user_status(db: Session, user_id: int, company_id: int, new_status: str):
    user = (
        db.query(models.User)
        .filter(
            models.User.id == user_id,
            models.User.company_id == company_id
        )
        .first()
    )
    if not user:
        return None

    user.status = new_status
    db.commit()
    db.refresh(user)
    return user


def update_user_password(db: Session, user_id: int, new_password: str):
    user = get_user_by_id(db, user_id)
    if not user:
        return None

    user.password_hash = hash_password(new_password)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, company_name: str, username: str, password: str):
    company = get_company_by_name(db, company_name)
    if not company:
        return None

    user = get_user_by_username(db, username, company.id)
    if not user:
        return None

    if user.status != "aktiv":
        return "inactive"

    if not verify_password(password, user.password_hash):
        return None

    return user


def get_all_buildings(db: Session, company_id: int, search: str = ""):
    query = (
        db.query(models.Building)
        .options(
            joinedload(models.Building.documents),
            joinedload(models.Building.tasks),
            joinedload(models.Building.emails),
            joinedload(models.Building.created_by_user),
        )
        .filter(models.Building.company_id == company_id)
    )

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                models.Building.name.ilike(search_term),
                models.Building.address.ilike(search_term),
                models.Building.landlord_name.ilike(search_term),
                models.Building.tenant_name.ilike(search_term),
                models.Building.tenant_email.ilike(search_term),
                models.Building.tenant_phone.ilike(search_term),
                models.Building.notes.ilike(search_term),
                models.Building.internal_description.ilike(search_term),
                models.Building.contact_person.ilike(search_term),
                models.Building.status.ilike(search_term)
            )
        )

    return query.order_by(models.Building.id.desc()).all()


def get_building_by_id(db: Session, building_id: int, company_id: int):
    return (
        db.query(models.Building)
        .options(
            joinedload(models.Building.documents),
            joinedload(models.Building.tasks).joinedload(models.Task.assigned_user),
            joinedload(models.Building.tasks).joinedload(models.Task.comments).joinedload(models.TaskComment.user),
            joinedload(models.Building.emails),
            joinedload(models.Building.created_by_user),
        )
        .filter(
            models.Building.id == building_id,
            models.Building.company_id == company_id
        )
        .first()
    )


def create_building(
    db: Session,
    name: str,
    address: str,
    landlord_name: str,
    tenant_name: str,
    tenant_email: str,
    tenant_phone: str,
    notes: str,
    internal_description: str,
    status: str,
    contact_person: str,
    company_id: int,
    created_by_user_id: int
):
    building = models.Building(
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
        company_id=company_id,
        created_by_user_id=created_by_user_id
    )
    db.add(building)
    db.commit()
    db.refresh(building)
    return building


def update_building(
    db: Session,
    building_id: int,
    company_id: int,
    name: str,
    address: str,
    landlord_name: str,
    tenant_name: str,
    tenant_email: str,
    tenant_phone: str,
    notes: str,
    internal_description: str,
    status: str,
    contact_person: str
):
    building = get_building_by_id(db, building_id, company_id)
    if not building:
        return None

    building.name = name
    building.address = address
    building.landlord_name = landlord_name
    building.tenant_name = tenant_name
    building.tenant_email = tenant_email
    building.tenant_phone = tenant_phone
    building.notes = notes
    building.internal_description = internal_description
    building.status = status
    building.contact_person = contact_person

    db.commit()
    db.refresh(building)
    return building


def delete_building(db: Session, building_id: int, company_id: int):
    building = get_building_by_id(db, building_id, company_id)
    if not building:
        return None

    for document in building.documents:
        if document.filepath and os.path.exists(document.filepath):
            try:
                os.remove(document.filepath)
            except OSError:
                pass

    db.delete(building)
    db.commit()
    return building


def create_document(
    db: Session,
    original_filename: str,
    stored_filename: str,
    title: str,
    category: str,
    filepath: str,
    building_id: int
):
    document = models.Document(
        original_filename=original_filename,
        stored_filename=stored_filename,
        title=title,
        category=category,
        filepath=filepath,
        building_id=building_id
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def get_document_by_id(db: Session, document_id: int, company_id: int):
    return (
        db.query(models.Document)
        .join(models.Building)
        .options(joinedload(models.Document.building))
        .filter(
            models.Document.id == document_id,
            models.Building.company_id == company_id
        )
        .first()
    )


def update_document(
    db: Session,
    document_id: int,
    company_id: int,
    title: str,
    category: str
):
    document = get_document_by_id(db, document_id, company_id)
    if not document:
        return None

    document.title = title
    document.category = category
    db.commit()
    db.refresh(document)
    return document


def delete_document(db: Session, document_id: int, company_id: int):
    document = get_document_by_id(db, document_id, company_id)
    if not document:
        return None

    if document.filepath and os.path.exists(document.filepath):
        try:
            os.remove(document.filepath)
        except OSError:
            pass

    db.delete(document)
    db.commit()
    return document


def create_task(
    db: Session,
    title: str,
    note: str,
    due_date,
    building_id: int,
    assigned_user_id=None,
    priority: str = "mittel",
    recurrence: str = "",
    parent_task_id: Optional[int] = None
):
    task = models.Task(
        title=title,
        note=note,
        due_date=due_date,
        status="offen",
        building_id=building_id,
        assigned_user_id=assigned_user_id,
        priority=priority,
        recurrence=recurrence or None,
        parent_task_id=parent_task_id
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task_by_id(db: Session, task_id: int, company_id: int):
    return (
        db.query(models.Task)
        .join(models.Building)
        .options(
            joinedload(models.Task.building),
            joinedload(models.Task.assigned_user),
            joinedload(models.Task.comments).joinedload(models.TaskComment.user),
            joinedload(models.Task.follow_up_tasks),
        )
        .filter(
            models.Task.id == task_id,
            models.Building.company_id == company_id
        )
        .first()
    )


def update_task(
    db: Session,
    task_id: int,
    company_id: int,
    title: str,
    note: str,
    due_date,
    assigned_user_id,
    priority: str,
    recurrence: str = ""
):
    task = get_task_by_id(db, task_id, company_id)
    if not task:
        return None

    task.title = title
    task.note = note
    task.due_date = due_date
    task.assigned_user_id = assigned_user_id
    task.priority = priority
    task.recurrence = recurrence or None

    db.commit()
    db.refresh(task)
    return task


def mark_task_done(db: Session, task_id: int, company_id: int):
    task = get_task_by_id(db, task_id, company_id)
    if task:
        task.status = "erledigt"
        db.commit()
        db.refresh(task)
    return task


def mark_task_open(db: Session, task_id: int, company_id: int):
    task = get_task_by_id(db, task_id, company_id)
    if task:
        task.status = "offen"
        db.commit()
        db.refresh(task)
    return task


def delete_task(db: Session, task_id: int, company_id: int):
    task = get_task_by_id(db, task_id, company_id)
    if not task:
        return None

    db.delete(task)
    db.commit()
    return task


def create_task_comment(db: Session, task_id: int, user_id: int, text: str):
    comment = models.TaskComment(
        task_id=task_id,
        user_id=user_id,
        text=text
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def mark_task_reminder_sent(db: Session, task_id: int, company_id: int):
    task = get_task_by_id(db, task_id, company_id)
    if not task:
        return None

    task.reminder_sent_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task


def get_open_tasks_sorted(db: Session, company_id: int):
    tasks = (
        db.query(models.Task)
        .join(models.Building)
        .options(
            joinedload(models.Task.building),
            joinedload(models.Task.assigned_user),
        )
        .filter(
            models.Task.status == "offen",
            models.Building.company_id == company_id
        )
        .all()
    )

    today = date.today()

    def priority_rank(task):
        if task.priority == "hoch":
            return 0
        if task.priority == "mittel":
            return 1
        return 2

    def due_rank(task):
        if task.due_date is None:
            return (3, date.max)

        if task.due_date < today:
            return (0, task.due_date)

        days_left = (task.due_date - today).days

        if days_left <= 3:
            return (1, task.due_date)

        if days_left <= 7:
            return (2, task.due_date)

        return (3, task.due_date)

    def sort_key(task):
        due_group, due_value = due_rank(task)
        mine_or_assigned = 0 if task.assigned_user_id else 1
        return (due_group, priority_rank(task), mine_or_assigned, due_value)

    return sorted(tasks, key=sort_key)


def get_today_tasks_count(db: Session, company_id: int):
    today = date.today()
    return (
        db.query(models.Task)
        .join(models.Building)
        .filter(
            models.Building.company_id == company_id,
            models.Task.status == "offen",
            models.Task.due_date == today
        )
        .count()
    )


def get_week_tasks_count(db: Session, company_id: int):
    today = date.today()
    week_end = today + timedelta(days=7)
    return (
        db.query(models.Task)
        .join(models.Building)
        .filter(
            models.Building.company_id == company_id,
            models.Task.status == "offen",
            models.Task.due_date.is_not(None),
            models.Task.due_date >= today,
            models.Task.due_date <= week_end
        )
        .count()
    )


def get_recent_comments_for_company(db: Session, company_id: int, limit: int = 5):
    comments = (
        db.query(models.TaskComment)
        .join(models.Task)
        .join(models.Building)
        .options(
            joinedload(models.TaskComment.user),
            joinedload(models.TaskComment.task),
        )
        .filter(models.Building.company_id == company_id)
        .order_by(models.TaskComment.created_at.desc())
        .limit(limit)
        .all()
    )
    return comments


def get_due_recurring_tasks(db: Session, company_id: int):
    return (
        db.query(models.Task)
        .join(models.Building)
        .filter(
            models.Building.company_id == company_id,
            models.Task.recurrence.is_not(None),
            models.Task.recurrence != ""
        )
        .all()
    )


def create_next_recurring_task_if_needed(db: Session, task_id: int, company_id: int):
    task = get_task_by_id(db, task_id, company_id)
    if not task:
        return None

    if not task.recurrence:
        return None

    if task.status != "erledigt":
        return None

    if task.follow_up_tasks:
        return task.follow_up_tasks[0]

    if not task.due_date:
        return None

    if task.recurrence == "täglich":
        new_due_date = task.due_date + timedelta(days=1)
    elif task.recurrence == "wöchentlich":
        new_due_date = task.due_date + timedelta(days=7)
    elif task.recurrence == "monatlich":
        new_due_date = task.due_date + timedelta(days=30)
    else:
        return None

    return create_task(
        db=db,
        title=task.title,
        note=task.note,
        due_date=new_due_date,
        building_id=task.building_id,
        assigned_user_id=task.assigned_user_id,
        priority=task.priority,
        recurrence=task.recurrence,
        parent_task_id=task.id
    )


def normalize_text(value: str) -> str:
    if not value:
        return ""
    value = value.lower().strip()
    value = value.replace("ß", "ss")
    value = re.sub(r"[^a-z0-9äöü\s]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value


def confidence_label_from_score(score: int) -> str:
    if score >= 100:
        return "Sicher erkannt"
    if score >= 40:
        return "Wahrscheinlich erkannt"
    return "Unsicher erkannt"


def get_email_by_id(db: Session, email_id: int, company_id: int):
    return (
        db.query(models.EmailMessage)
        .options(
            joinedload(models.EmailMessage.building),
            joinedload(models.EmailMessage.company),
            joinedload(models.EmailMessage.source_email),
        )
        .filter(
            models.EmailMessage.id == email_id,
            models.EmailMessage.company_id == company_id
        )
        .first()
    )


def detect_email_building_match(
    db: Session,
    company_id: int,
    sender_email: str,
    subject: str,
    body_text: str
):
    buildings = get_all_buildings(db, company_id)
    full_text = normalize_text(f"{subject or ''} {body_text or ''}")
    sender_email_normalized = (sender_email or "").strip().lower()

    best_building = None
    best_score = -1
    best_reason = ""

    for building in buildings:
        score = 0
        reasons = []

        tenant_email = (building.tenant_email or "").strip().lower()
        tenant_name = normalize_text(building.tenant_name or "")
        address = normalize_text(building.address or "")
        building_name = normalize_text(building.name or "")

        if tenant_email and sender_email_normalized and tenant_email == sender_email_normalized:
            score += 100
            reasons.append("Mieter E Mail exakt erkannt")

        if tenant_name and tenant_name in full_text:
            score += 30
            reasons.append("Mietername im Text erkannt")

        if address and address in full_text:
            score += 40
            reasons.append("Adresse im Text erkannt")

        if building_name and building_name in full_text:
            score += 15
            reasons.append("Objektname im Text erkannt")

        if score > best_score:
            best_score = score
            best_building = building
            best_reason = ", ".join(reasons)

    if not best_building or best_score <= 0:
        return None, "Unsicher erkannt", ""

    return best_building, confidence_label_from_score(best_score), best_reason


def create_email_message(
    db: Session,
    company_id: int,
    subject: str,
    sender_name: str,
    sender_email: str,
    body_text: str,
    direction: str = "eingehend",
    status: str = "neu",
    received_at: Optional[datetime] = None,
    building_id: Optional[int] = None,
    is_auto_assigned: bool = False,
    assignment_confidence: str = "Unsicher erkannt",
    matched_by: str = "",
    thread_key: str = "",
    external_message_id: str = "",
    source_email_id: Optional[int] = None
):
    assigned_building_id = building_id
    auto_assigned = is_auto_assigned
    confidence = assignment_confidence
    match_reason = matched_by

    if assigned_building_id is None and direction == "eingehend":
        matched_building, detected_confidence, detected_reason = detect_email_building_match(
            db=db,
            company_id=company_id,
            sender_email=sender_email,
            subject=subject,
            body_text=body_text
        )
        if matched_building:
            assigned_building_id = matched_building.id
            auto_assigned = True
            confidence = detected_confidence
            match_reason = detected_reason

    email_message = models.EmailMessage(
        company_id=company_id,
        building_id=assigned_building_id,
        subject=subject or "",
        sender_name=sender_name or "",
        sender_email=sender_email or "",
        body_text=body_text or "",
        direction=direction,
        status=status,
        received_at=received_at or datetime.utcnow(),
        is_auto_assigned=auto_assigned,
        assignment_confidence=confidence or "Unsicher erkannt",
        matched_by=match_reason or "",
        thread_key=thread_key or "",
        external_message_id=external_message_id or "",
        source_email_id=source_email_id
    )

    db.add(email_message)
    db.commit()
    db.refresh(email_message)
    return email_message


def create_email_reply(
    db: Session,
    source_email_id: int,
    company_id: int,
    sender_name: str,
    sender_email: str,
    subject: str,
    body_text: str,
    status: str = "beantwortet"
):
    source_email = get_email_by_id(db, source_email_id, company_id)
    if not source_email:
        return None

    reply = create_email_message(
        db=db,
        company_id=company_id,
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email,
        body_text=body_text,
        direction="ausgehend",
        status=status,
        received_at=datetime.utcnow(),
        building_id=source_email.building_id,
        is_auto_assigned=False,
        assignment_confidence="Manuell erstellt",
        matched_by="Antwort aus System",
        thread_key=source_email.thread_key or str(source_email.id),
        source_email_id=source_email.id
    )

    source_email.status = "beantwortet"
    db.commit()
    db.refresh(source_email)

    return reply


def get_email_thread_messages(db: Session, company_id: int, email_id: int):
    email_message = get_email_by_id(db, email_id, company_id)
    if not email_message:
        return []

    thread_key = (email_message.thread_key or "").strip()

    if thread_key:
        return (
            db.query(models.EmailMessage)
            .options(
                joinedload(models.EmailMessage.building),
                joinedload(models.EmailMessage.source_email),
            )
            .filter(
                models.EmailMessage.company_id == company_id,
                models.EmailMessage.thread_key == thread_key
            )
            .order_by(models.EmailMessage.received_at.asc())
            .all()
        )

    collected_ids = {email_message.id}

    if email_message.source_email_id:
        collected_ids.add(email_message.source_email_id)

    related = (
        db.query(models.EmailMessage)
        .filter(
            models.EmailMessage.company_id == company_id,
            or_(
                models.EmailMessage.id == email_message.id,
                models.EmailMessage.id == email_message.source_email_id,
                models.EmailMessage.source_email_id == email_message.id
            )
        )
        .order_by(models.EmailMessage.received_at.asc())
        .all()
    )

    for item in related:
        collected_ids.add(item.id)
        if item.source_email_id:
            collected_ids.add(item.source_email_id)

    return (
        db.query(models.EmailMessage)
        .options(
            joinedload(models.EmailMessage.building),
            joinedload(models.EmailMessage.source_email),
        )
        .filter(
            models.EmailMessage.company_id == company_id,
            models.EmailMessage.id.in_(collected_ids)
        )
        .order_by(models.EmailMessage.received_at.asc())
        .all()
    )


def get_company_emails(
    db: Session,
    company_id: int,
    search: str = "",
    status: str = "",
    only_unassigned: bool = False,
    only_assigned: bool = False,
    building_id: Optional[int] = None
):
    query = (
        db.query(models.EmailMessage)
        .options(
            joinedload(models.EmailMessage.building),
            joinedload(models.EmailMessage.source_email),
        )
        .filter(models.EmailMessage.company_id == company_id)
    )

    if only_unassigned:
        query = query.filter(models.EmailMessage.building_id.is_(None))

    if only_assigned:
        query = query.filter(models.EmailMessage.building_id.is_not(None))

    if building_id:
        query = query.filter(models.EmailMessage.building_id == building_id)

    if status:
        query = query.filter(models.EmailMessage.status == status)

    emails = query.order_by(models.EmailMessage.received_at.desc()).all()

    if search:
        value = search.lower()
        filtered = []
        for email in emails:
            building_name = email.building.name if email.building else ""
            building_address = email.building.address if email.building else ""

            haystack = " ".join([
                email.subject or "",
                email.sender_name or "",
                email.sender_email or "",
                email.body_text or "",
                email.status or "",
                email.assignment_confidence or "",
                email.matched_by or "",
                building_name or "",
                building_address or ""
            ]).lower()

            if value in haystack:
                filtered.append(email)

        return filtered

    return emails


def get_building_emails(db: Session, building_id: int, company_id: int):
    return (
        db.query(models.EmailMessage)
        .options(joinedload(models.EmailMessage.building))
        .filter(
            models.EmailMessage.company_id == company_id,
            models.EmailMessage.building_id == building_id
        )
        .order_by(models.EmailMessage.received_at.desc())
        .all()
    )


def get_unassigned_emails(db: Session, company_id: int, limit: Optional[int] = None):
    query = (
        db.query(models.EmailMessage)
        .filter(
            models.EmailMessage.company_id == company_id,
            models.EmailMessage.building_id.is_(None)
        )
        .order_by(models.EmailMessage.received_at.desc())
    )

    if limit:
        query = query.limit(limit)

    return query.all()


def assign_email_to_building(db: Session, email_id: int, company_id: int, building_id: int):
    email_message = get_email_by_id(db, email_id, company_id)
    building = get_building_by_id(db, building_id, company_id)

    if not email_message or not building:
        return None

    email_message.building_id = building.id
    email_message.is_auto_assigned = False
    email_message.assignment_confidence = "Manuell zugeordnet"
    email_message.matched_by = "Manuelle Zuordnung"
    db.commit()
    db.refresh(email_message)
    return email_message


def unassign_email_from_building(db: Session, email_id: int, company_id: int):
    email_message = get_email_by_id(db, email_id, company_id)
    if not email_message:
        return None

    email_message.building_id = None
    email_message.assignment_confidence = "Nicht zugeordnet"
    email_message.matched_by = "Zuordnung entfernt"
    email_message.is_auto_assigned = False
    db.commit()
    db.refresh(email_message)
    return email_message


def update_email_status(db: Session, email_id: int, company_id: int, status: str):
    email_message = get_email_by_id(db, email_id, company_id)
    if not email_message:
        return None

    email_message.status = status
    db.commit()
    db.refresh(email_message)
    return email_message


def create_email_internal_note(
    db: Session,
    company_id: int,
    email_id: int,
    user_id: int,
    text: str
):
    email_message = get_email_by_id(db, email_id, company_id)
    if not email_message:
        return None

    note = models.EmailInternalNote(
        company_id=company_id,
        email_id=email_id,
        user_id=user_id,
        text=text
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


def get_email_internal_notes(db: Session, email_id: int, company_id: int):
    email_message = get_email_by_id(db, email_id, company_id)
    if not email_message:
        return []

    return (
        db.query(models.EmailInternalNote)
        .options(joinedload(models.EmailInternalNote.user))
        .filter(
            models.EmailInternalNote.company_id == company_id,
            models.EmailInternalNote.email_id == email_id
        )
        .order_by(models.EmailInternalNote.created_at.desc())
        .all()
    )


def get_email_counts_for_company(db: Session, company_id: int):
    emails = (
        db.query(models.EmailMessage)
        .filter(models.EmailMessage.company_id == company_id)
        .all()
    )

    return {
        "total": len(emails),
        "unassigned": len([e for e in emails if e.building_id is None]),
        "new": len([e for e in emails if e.status == "neu"]),
        "open": len([e for e in emails if e.status == "offen"]),
        "answered": len([e for e in emails if e.status == "beantwortet"]),
    }


def get_recent_emails_for_company(db: Session, company_id: int, limit: int = 5):
    return (
        db.query(models.EmailMessage)
        .options(joinedload(models.EmailMessage.building))
        .filter(models.EmailMessage.company_id == company_id)
        .order_by(models.EmailMessage.received_at.desc())
        .limit(limit)
        .all()
    )


def get_recent_activity_for_building(db: Session, building_id: int, company_id: int, limit: int = 15):
    building = get_building_by_id(db, building_id, company_id)
    if not building:
        return []

    activities = []

    for document in building.documents:
        activities.append({
            "type": "document",
            "title": "Dokument hochgeladen",
            "description": document.title or document.original_filename,
            "date": document.created_at
        })

    for task in building.tasks:
        activities.append({
            "type": "task",
            "title": "Aufgabe erstellt" if task.status == "offen" else "Aufgabe erledigt",
            "description": task.title,
            "date": datetime.combine(task.due_date, datetime.min.time()) if task.due_date else datetime.utcnow()
        })

        for comment in task.comments:
            activities.append({
                "type": "comment",
                "title": "Kommentar hinzugefügt",
                "description": comment.text,
                "date": comment.created_at
            })

    for email in building.emails:
        activities.append({
            "type": "email",
            "title": "E Mail eingegangen" if email.direction == "eingehend" else "E Mail gesendet",
            "description": email.subject or "Ohne Betreff",
            "date": email.received_at
        })

    activities = sorted(activities, key=lambda x: x["date"], reverse=True)
    return activities[:limit]