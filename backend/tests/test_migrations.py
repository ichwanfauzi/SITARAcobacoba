from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_initial_migration_creates_identity_schema_and_seed_roles(tmp_path: Path) -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    database_path = tmp_path / "migration.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        role_codes = set(connection.execute(text("SELECT role_code FROM roles")).scalars())

    assert {"users", "roles", "user_roles", "user_sessions", "alembic_version"} <= tables
    assert role_codes == {"SUPER_ADMIN", "SEKRETARIAT", "REKTOR", "WAREK", "PIC"}

    command.downgrade(config, "base")
    assert "users" not in inspect(engine).get_table_names()
    engine.dispose()
