from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    import app.models  # noqa: F401 - registra todos los modelos en metadata
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    init_db()
    print("Base de datos creada correctamente.")
