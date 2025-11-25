"""
Database Setup und Session Management
"""
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
import os

from gridtrader.infrastructure.persistence.models.db_models import Base


class DatabaseManager:
    """Verwaltet Database-Verbindungen"""
    
    def __init__(self, database_url: str = None):
        """
        Args:
            database_url: SQLAlchemy database URL
        """
        if database_url is None:
            # Default: SQLite in data/ Verzeichnis
            db_path = Path("data/gridtrader.db")
            db_path.parent.mkdir(exist_ok=True)
            database_url = f"sqlite:///{db_path}"
        
        self.database_url = database_url
        self.engine = None
        self.SessionLocal = None
        
    def initialize(self, echo: bool = False):
        """Initialisiere Datenbank"""
        # Engine erstellen
        if "sqlite" in self.database_url:
            # SQLite-spezifische Einstellungen
            self.engine = create_engine(
                self.database_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=echo
            )
            
            # Foreign Keys für SQLite aktivieren
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        else:
            # Andere Datenbanken
            self.engine = create_engine(self.database_url, echo=echo)
        
        # Session Factory
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )
        
    def create_tables(self):
        """Erstelle alle Tabellen"""
        Base.metadata.create_all(bind=self.engine)
        
    def drop_tables(self):
        """Lösche alle Tabellen (Vorsicht!)"""
        Base.metadata.drop_all(bind=self.engine)
        
    def get_session(self) -> Session:
        """Hole neue Session"""
        return self.SessionLocal()
        
    def close(self):
        """Schließe Engine"""
        if self.engine:
            self.engine.dispose()


# Singleton Instance
_db_manager = None

def get_db_manager() -> DatabaseManager:
    """Hole Database Manager Singleton"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
        _db_manager.initialize()
    return _db_manager

def get_db() -> Session:
    """Dependency für FastAPI/Testing"""
    db = get_db_manager().get_session()
    try:
        yield db
    finally:
        db.close()
