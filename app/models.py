from sqlalchemy import Column, Integer, String, Date, ForeignKey, Text
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


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="Mitarbeiter")
    status = Column(String, nullable=False, default="aktiv")

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    company = relationship("Company", back_populates="users")

    buildings = relationship(
        "Building",
        back_populates="created_by_user"
    )

    assigned_tasks = relationship(
        "Task",
        back_populates="assigned_user"
    )


class Building(Base):
    __tablename__ = "buildings"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    address = Column(String, nullable=False)
    landlord_name = Column(String, nullable=True)
    tenant_name = Column(String, nullable=True)
    tenant_email = Column(String, nullable=True)
    tenant_phone = Column(String, nullable=True)

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


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    original_filename = Column(String, nullable=False)
    stored_filename = Column(String, nullable=False)
    category = Column(String, nullable=False)
    filepath = Column(String, nullable=False)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)

    building = relationship("Building", back_populates="documents")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    due_date = Column(Date, nullable=True)
    status = Column(String, nullable=False, default="offen")

    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)
    assigned_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    building = relationship("Building", back_populates="tasks")
    assigned_user = relationship("User", back_populates="assigned_tasks")