import os
from datetime import date
from sqlalchemy import or_
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from app import models

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str):
    return pwd_context.verify(password, password_hash)


def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()


def get_user_by_id(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_company_by_name(db: Session, company_name: str):
    return db.query(models.Company).filter(models.Company.name == company_name).first()


def get_company_by_id(db: Session, company_id: int):
    return db.query(models.Company).filter(models.Company.id == company_id).first()


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
    db.commit()
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

    db.commit()
    db.refresh(company)
    return company


def get_company_users(db: Session, company_id: int):
    return (
        db.query(models.User)
        .filter(models.User.company_id == company_id)
        .order_by(models.User.id.desc())
        .all()
    )


def create_user(
    db: Session,
    username: str,
    password: str,
    company_id: int,
    role: str = "Mitarbeiter"
):
    user = models.User(
        username=username,
        password_hash=hash_password(password),
        company_id=company_id,
        role=role,
        status="aktiv"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_role(db: Session, user_id: int, company_id: int, new_role: str):
    user = (
        db.query(models.User)
        .filter(models.User.id == user_id, models.User.company_id == company_id)
        .first()
    )
    if not user:
        return None

    user.role = new_role
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str):
    user = get_user_by_username(db, username)
    if not user:
        return None

    if not verify_password(password, user.password_hash):
        return None

    return user


def get_all_buildings(db: Session, company_id: int, search: str = ""):
    query = db.query(models.Building).filter(models.Building.company_id == company_id)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                models.Building.name.ilike(search_term),
                models.Building.address.ilike(search_term),
                models.Building.landlord_name.ilike(search_term),
                models.Building.tenant_name.ilike(search_term),
                models.Building.tenant_email.ilike(search_term),
                models.Building.tenant_phone.ilike(search_term)
            )
        )

    return query.order_by(models.Building.id.desc()).all()


def get_building_by_id(db: Session, building_id: int, company_id: int):
    return (
        db.query(models.Building)
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
        company_id=company_id,
        created_by_user_id=created_by_user_id
    )
    db.add(building)
    db.commit()
    db.refresh(building)
    return building


def create_document(
    db: Session,
    original_filename: str,
    stored_filename: str,
    category: str,
    filepath: str,
    building_id: int
):
    document = models.Document(
        original_filename=original_filename,
        stored_filename=stored_filename,
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
        .filter(
            models.Document.id == document_id,
            models.Building.company_id == company_id
        )
        .first()
    )


def delete_document(db: Session, document_id: int, company_id: int):
    document = get_document_by_id(db, document_id, company_id)
    if not document:
        return None

    if os.path.exists(document.filepath):
        os.remove(document.filepath)

    db.delete(document)
    db.commit()
    return document


def create_task(db: Session, title: str, note: str, due_date, building_id: int, assigned_user_id=None):
    task = models.Task(
        title=title,
        note=note,
        due_date=due_date,
        status="offen",
        building_id=building_id,
        assigned_user_id=assigned_user_id
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task_by_id(db: Session, task_id: int, company_id: int):
    return (
        db.query(models.Task)
        .join(models.Building)
        .filter(
            models.Task.id == task_id,
            models.Building.company_id == company_id
        )
        .first()
    )


def mark_task_done(db: Session, task_id: int, company_id: int):
    task = get_task_by_id(db, task_id, company_id)
    if task:
        task.status = "erledigt"
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


def get_open_tasks_sorted(db: Session, company_id: int):
    tasks = (
        db.query(models.Task)
        .join(models.Building)
        .filter(
            models.Task.status == "offen",
            models.Building.company_id == company_id
        )
        .all()
    )

    today = date.today()

    def sort_key(task):
        assigned_priority = 0 if task.assigned_user_id else 1

        if task.due_date is None:
            return (assigned_priority, 3, date.max)

        if task.due_date < today:
            return (assigned_priority, 0, task.due_date)

        days_left = (task.due_date - today).days

        if days_left <= 3:
            return (assigned_priority, 1, task.due_date)

        if days_left <= 7:
            return (assigned_priority, 2, task.due_date)

        return (assigned_priority, 3, task.due_date)

    return sorted(tasks, key=sort_key)