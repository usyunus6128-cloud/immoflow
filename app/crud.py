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


def create_user(db: Session, username: str, password: str):
    user = models.User(
        username=username,
        password_hash=hash_password(password)
    )
    db.add(user)
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


def get_all_buildings(db: Session, user_id: int, search: str = ""):
    query = db.query(models.Building).filter(models.Building.user_id == user_id)

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                models.Building.name.ilike(search_term),
                models.Building.address.ilike(search_term),
                models.Building.landlord_name.ilike(search_term),
                models.Building.tenant_name.ilike(search_term)
            )
        )

    return query.order_by(models.Building.id.desc()).all()


def get_building_by_id(db: Session, building_id: int, user_id: int):
    return (
        db.query(models.Building)
        .filter(models.Building.id == building_id, models.Building.user_id == user_id)
        .first()
    )


def create_building(
    db: Session,
    name: str,
    address: str,
    landlord_name: str,
    tenant_name: str,
    user_id: int
):
    building = models.Building(
        name=name,
        address=address,
        landlord_name=landlord_name,
        tenant_name=tenant_name,
        user_id=user_id
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


def get_document_by_id(db: Session, document_id: int, user_id: int):
    return (
        db.query(models.Document)
        .join(models.Building)
        .filter(models.Document.id == document_id, models.Building.user_id == user_id)
        .first()
    )


def delete_document(db: Session, document_id: int, user_id: int):
    document = get_document_by_id(db, document_id, user_id)
    if not document:
        return None

    if os.path.exists(document.filepath):
        os.remove(document.filepath)

    db.delete(document)
    db.commit()
    return document


def create_task(db: Session, title: str, note: str, due_date, building_id: int):
    task = models.Task(
        title=title,
        note=note,
        due_date=due_date,
        status="offen",
        building_id=building_id
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task_by_id(db: Session, task_id: int, user_id: int):
    return (
        db.query(models.Task)
        .join(models.Building)
        .filter(models.Task.id == task_id, models.Building.user_id == user_id)
        .first()
    )


def mark_task_done(db: Session, task_id: int, user_id: int):
    task = get_task_by_id(db, task_id, user_id)
    if task:
        task.status = "erledigt"
        db.commit()
        db.refresh(task)
    return task


def delete_task(db: Session, task_id: int, user_id: int):
    task = get_task_by_id(db, task_id, user_id)
    if not task:
        return None

    db.delete(task)
    db.commit()
    return task


def get_open_tasks_sorted(db: Session, user_id: int):
    tasks = (
        db.query(models.Task)
        .join(models.Building)
        .filter(models.Task.status == "offen", models.Building.user_id == user_id)
        .all()
    )

    today = date.today()

    def sort_key(task):
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

    return sorted(tasks, key=sort_key)