from alembic import context
from sports_analyst.config import Settings
from sports_analyst.jobs import Base, database_engine

connection = context.config.attributes.get("connection")
if connection is not None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    settings = Settings()
    secret = settings.database_migration_url
    if not secret:
        raise ValueError("Set DATABASE_MIGRATION_URL to the direct PostgreSQL connection string")
    engine = database_engine(secret.get_secret_value())
    if "-pooler" in (engine.url.host or ""):
        raise ValueError("Migrations require Neon's direct connection, without -pooler")
if connection is None and context.is_offline_mode():
    # noinspection unbound-local-variable
    context.configure(url=engine.url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif connection is None:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
