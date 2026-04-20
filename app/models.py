from datetime import datetime

from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Text, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(Text, nullable=True)

    users = relationship("User", back_populates="company", cascade="all, delete-orphan")
    buildings = relationship("Building", back_populates="company", cascade="all, delete-orphan")
    emails = relationship("EmailMessage", back_populates="company", cascade="all, delete-orphan")
    email_internal_notes = relationship("EmailInternalNote", back_populates="company", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("company_id", "username", name="uq_users_company_username"),
    )

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, index=True)
    email = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    role = Column(String, nullable=False, default="Mitarbeiter")
    status = Column(String, nullable=False, default="aktiv")

    company = relationship("Company", back_populates="users")

    created_buildings = relationship(
        "Building",
        back_populates="created_by_user",
        foreign_keys="Building.created_by_user_id"
    )
    assigned_tasks = relationship(
        "Task",
        back_populates="assigned_user",
        foreign_keys="Task.assigned_user_id"
    )
    task_comments = relationship("TaskComment", back_populates="user", cascade="all, delete-orphan")
    email_internal_notes = relationship("EmailInternalNote", back_populates="user", cascade="all, delete-orphan")


class Building(Base):
    __tablename__ = "buildings"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)

    landlord_name = Column(String, nullable=True)
    tenant_name = Column(String, nullable=True)
    tenant_email = Column(String, nullable=True)
    tenant_phone = Column(String, nullable=True)

    notes = Column(Text, nullable=True)
    internal_description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="aktiv")
    contact_person = Column(String, nullable=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    company = relationship("Company", back_populates="buildings")
    created_by_user = relationship(
        "User",
        back_populates="created_buildings",
        foreign_keys=[created_by_user_id]
    )

    documents = relationship("Document", back_populates="building", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="building", cascade="all, delete-orphan")
    emails = relationship("EmailMessage", back_populates="building")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False)
    title = Column(String, nullable=True)
    category = Column(String, nullable=False)
    filepath = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)

    building = relationship("Building", back_populates="documents")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String, nullable=False, default="offen")
    priority = Column(String, nullable=False, default="mittel")
    recurrence = Column(String, nullable=True)
    reminder_sent_at = Column(DateTime, nullable=True)

    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    parent_task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)

    building = relationship("Building", back_populates="tasks")
    assigned_user = relationship(
        "User",
        back_populates="assigned_tasks",
        foreign_keys=[assigned_user_id]
    )
    comments = relationship("TaskComment", back_populates="task", cascade="all, delete-orphan")

    parent_task = relationship(
        "Task",
        remote_side=[id],
        back_populates="follow_up_tasks",
        foreign_keys=[parent_task_id]
    )
    follow_up_tasks = relationship(
        "Task",
        back_populates="parent_task"
    )


class TaskComment(Base):
    __tablename__ = "task_comments"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    task = relationship("Task", back_populates="comments")
    user = relationship("User", back_populates="task_comments")


class EmailMessage(Base):
    __tablename__ = "email_messages"

    id = Column(Integer, primary_key=True, index=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=True)

    subject = Column(String, nullable=True)
    sender_name = Column(String, nullable=True)
    sender_email = Column(String, nullable=True)
    body_text = Column(Text, nullable=True)

    direction = Column(String, nullable=False, default="eingehend")
    status = Column(String, nullable=False, default="neu")
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    is_auto_assigned = Column(Boolean, default=False, nullable=False)
    assignment_confidence = Column(String, nullable=True)
    matched_by = Column(String, nullable=True)

    thread_key = Column(String, nullable=True)
    external_message_id = Column(String, nullable=True)
    source_email_id = Column(Integer, ForeignKey("email_messages.id"), nullable=True)

    company = relationship("Company", back_populates="emails")
    building = relationship("Building", back_populates="emails")

    source_email = relationship(
        "EmailMessage",
        remote_side=[id],
        foreign_keys=[source_email_id]
    )
    replies = relationship("EmailMessage")
    internal_notes = relationship("EmailInternalNote", back_populates="email", cascade="all, delete-orphan")


class EmailInternalNote(Base):
    __tablename__ = "email_internal_notes"

    id = Column(Integer, primary_key=True, index=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    email_id = Column(Integer, ForeignKey("email_messages.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    company = relationship("Company", back_populates="email_internal_notes")
    email = relationship("EmailMessage", back_populates="internal_notes")
    user = relationship("User", back_populates="email_internal_notes")