from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)

    users = relationship(
        "User",
        back_populates="company",
        cascade="all, delete-orphan"
    )

    buildings = relationship(
        "Building",
        back_populates="company",
        cascade="all, delete-orphan"
    )

    emails = relationship(
        "EmailMessage",
        back_populates="company",
        cascade="all, delete-orphan"
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, nullable=False, index=True)
    email = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="Mitarbeiter")
    status = Column(String, nullable=False, default="aktiv")

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    company = relationship("Company", back_populates="users")

    buildings = relationship("Building", back_populates="created_by_user")
    assigned_tasks = relationship("Task", back_populates="assigned_user")
    task_comments = relationship("TaskComment", back_populates="user")


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
    created_by_user = relationship("User", back_populates="buildings")

    documents = relationship(
        "Document",
        back_populates="building",
        cascade="all, delete-orphan"
    )

    tasks = relationship(
        "Task",
        back_populates="building",
        cascade="all, delete-orphan"
    )

    emails = relationship(
        "EmailMessage",
        back_populates="building"
    )


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
    reminder_sent_at = Column(DateTime, nullable=True)

    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    building = relationship("Building", back_populates="tasks")
    assigned_user = relationship("User", back_populates="assigned_tasks")

    comments = relationship(
        "TaskComment",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskComment.created_at"
    )


class TaskComment(Base):
    __tablename__ = "task_comments"

    id = Column(Integer, primary_key=True, index=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    task = relationship("Task", back_populates="comments")
    user = relationship("User", back_populates="task_comments")


class EmailMessage(Base):
    __tablename__ = "email_messages"

    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String, nullable=False, default="")
    sender_name = Column(String, nullable=True)
    sender_email = Column(String, nullable=True)
    body_text = Column(Text, nullable=False, default="")
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    direction = Column(String, nullable=False, default="eingehend")
    status = Column(String, nullable=False, default="neu")
    assignment_confidence = Column(String, nullable=False, default="unsicher")
    matched_by = Column(String, nullable=True)

    is_auto_assigned = Column(Boolean, nullable=False, default=False)
    thread_key = Column(String, nullable=True)
    external_message_id = Column(String, nullable=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=True)

    company = relationship("Company", back_populates="emails")
    building = relationship("Building", back_populates="emails")