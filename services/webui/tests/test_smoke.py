def test_settings_and_db_importable():
    from webui import events, settings
    from webui.internal import db

    assert settings.DATABASE_URL
    assert hasattr(db, "Base") and hasattr(db, "create_all_tables")
    assert events.publish_event is not None
